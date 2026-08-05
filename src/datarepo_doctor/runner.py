"""One isolated probe run: stages, safe errors, validation, and hard timeout."""

from __future__ import annotations

import importlib.metadata
import multiprocessing
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from time import perf_counter_ns

import httpx

from datarepo_doctor import __version__
from datarepo_doctor.models import FailureMode, Health, PhaseTiming, ProbeOutcome, ProbeSpec, Stage
from datarepo_doctor.validation import ProbeError, validate_result


@dataclass
class StageError(Exception):
    stage: Stage
    default_mode: FailureMode
    cause: BaseException


@contextmanager
def execution_stage(stage: Stage, default_mode: FailureMode) -> Iterator[None]:
    try:
        yield
    except StageError:
        raise
    except BaseException as exc:
        raise StageError(stage, default_mode, exc) from exc


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _root(exc: BaseException) -> BaseException:
    return exc.cause if isinstance(exc, StageError) else exc


_URL = re.compile(r"\b(?:https?|postgres(?:ql)?|s3)://[^\s]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|access[_-]?key|authorization|credential)\b\s*[:=]\s*[^\s,;]+"
)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b")
_QUOTED_VALUE = re.compile(r"(['\"])(?:(?!\1).)*\1")


def sanitize_error_message(message: str) -> str:
    """Return one short diagnostic line with unsafe literals removed."""

    line = " ".join(message.splitlines()[0].split()) if message else ""
    line = _URL.sub("[redacted-url]", line)
    line = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", line)
    line = _LONG_TOKEN.sub("[redacted-token]", line)
    line = _QUOTED_VALUE.sub("[redacted-value]", line)
    return line[:240]


def safe_exception_detail(exc: BaseException) -> str:
    """Expose the exception type and only a safely retainable reason."""

    cause = _root(exc)
    name = cause.__class__.__name__
    if isinstance(cause, ProbeError):
        return f"{name}: {cause.safe_summary}"[:300]
    safe_message_types = (
        socket.gaierror,
        httpx.HTTPStatusError,
        httpx.ConnectError,
        httpx.TimeoutException,
        ConnectionRefusedError,
        ConnectionResetError,
        TimeoutError,
    )
    if isinstance(cause, safe_message_types):
        message = sanitize_error_message(str(cause))
        if message:
            return f"{name}: {message}"[:300]
    # Unknown/database/object-store exceptions can include SQL, rows, paths, or
    # credentials. Their type is useful; their unstructured message is not safe.
    return name[:300]


def classify_exception(exc: BaseException) -> tuple[Stage, FailureMode, str]:
    stage = Stage.WORKER
    fallback = FailureMode.UNKNOWN
    root = exc
    if isinstance(exc, StageError):
        stage, fallback, root = exc.stage, exc.default_mode, exc.cause

    for cause in _chain(root):
        if isinstance(cause, ProbeError):
            return Stage.VALIDATION, cause.mode, cause.safe_summary
        if isinstance(cause, KeyError) and stage == Stage.TABLE_RESOLUTION:
            return stage, FailureMode.TABLE_NOT_FOUND, "Configured DataRepo table was not found."
        if isinstance(cause, socket.gaierror):
            return stage, FailureMode.DNS_ERROR, "A service hostname could not be resolved."
        if isinstance(cause, (httpx.ConnectError, ConnectionRefusedError, ConnectionResetError)):
            return stage, FailureMode.CONNECTION_ERROR, "The configured service could not be reached."
        if isinstance(cause, httpx.TimeoutException):
            return stage, FailureMode.CONNECTION_ERROR, "The HTTP dependency did not respond."
        if isinstance(cause, httpx.HTTPStatusError):
            status = cause.response.status_code
            if status == 401:
                return (
                    stage,
                    FailureMode.AUTHENTICATION_ERROR,
                    "The representative identity was not authenticated.",
                )
            if status == 403:
                return (
                    stage,
                    FailureMode.AUTHORIZATION_ERROR,
                    "The representative identity was not authorized.",
                )
            if status == 404:
                return stage, FailureMode.SOURCE_NOT_FOUND, "The configured source was not found."
            return stage, FailureMode.HTTP_ERROR, f"The read-only API returned HTTP {status}."
        if isinstance(cause, FileNotFoundError):
            return stage, FailureMode.SOURCE_NOT_FOUND, "The configured object source was not found."

        if cause.__class__.__module__.startswith("botocore") and hasattr(cause, "response"):
            code = str(getattr(cause, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"}:
                return stage, FailureMode.AUTHENTICATION_ERROR, "Object credentials were rejected."
            if code in {"AccessDenied", "Forbidden"}:
                return stage, FailureMode.AUTHORIZATION_ERROR, "Object access was denied."
            if code in {"NoSuchBucket", "NoSuchKey", "404"}:
                return stage, FailureMode.SOURCE_NOT_FOUND, "The configured object source was not found."

        module_name = cause.__class__.__module__
        class_name = cause.__class__.__name__
        if module_name.startswith("psycopg"):
            if class_name in {"InvalidPassword", "InvalidAuthorizationSpecification"}:
                return stage, FailureMode.AUTHENTICATION_ERROR, "PostgreSQL credentials were rejected."
            if class_name == "InsufficientPrivilege":
                return stage, FailureMode.AUTHORIZATION_ERROR, "PostgreSQL access was denied."
            if class_name in {"OperationalError", "ConnectionTimeout"}:
                return stage, FailureMode.CONNECTION_ERROR, "PostgreSQL could not be reached."

    summaries = {
        FailureMode.CATALOG_IMPORT_ERROR: "The configured DataRepo catalog could not be imported.",
        FailureMode.QUERY_EXECUTION_ERROR: "The bounded query failed during execution.",
        FailureMode.RESPONSE_DECODE_ERROR: "The complete HTTP response could not be decoded.",
        FailureMode.HTTP_ERROR: "The read-only HTTP query failed.",
        FailureMode.UNKNOWN: "The probe failed unexpectedly.",
    }
    return stage, fallback, summaries.get(fallback, "The probe failed.")


def _duration_ms(start: int) -> float:
    return round((perf_counter_ns() - start) / 1_000_000, 3)


def _datarepo_version() -> str:
    try:
        return importlib.metadata.version("data-repository")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def execute_probe(spec: ProbeSpec) -> ProbeOutcome:
    started = perf_counter_ns()
    try:
        # Retrieval imports stay inside the isolated process. This also avoids
        # importing DataRepo's heavy dependencies in the FastAPI parent.
        from datarepo_doctor.retrieval import retrieve

        result = retrieve(spec)
        validation_started = perf_counter_ns()
        with execution_stage(Stage.VALIDATION, FailureMode.UNKNOWN):
            validate_result(result.rows, spec)
        validation_done = perf_counter_ns()
        display_rows = (
            tuple(dict(row) for row in result.rows)
            if spec.display_result_rows
            else ()
        )
        result.rows.clear()
        phases = result.phases + (
            PhaseTiming(
                name="validation",
                duration_ms=round((validation_done - validation_started) / 1_000_000, 3),
            ),
        )
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.HEALTHY,
            checked_at=datetime.now(UTC),
            user_query_latency_ms=result.user_query_latency_ms,
            phase_timings=phases,
            result_rows=display_rows,
            total_probe_duration_ms=_duration_ms(started),
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=_datarepo_version(),
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )
    except BaseException as exc:
        stage, mode, summary = classify_exception(exc)
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.UNHEALTHY,
            checked_at=datetime.now(UTC),
            total_probe_duration_ms=_duration_ms(started),
            failure_stage=stage,
            failure_mode=mode,
            failure_summary=summary,
            failure_detail=safe_exception_detail(exc),
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=_datarepo_version(),
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )


def worker_main(send: Connection, spec_json: str) -> None:
    """Spawn-safe child entrypoint. Only serialized spec/outcome cross the pipe."""

    try:
        spec = ProbeSpec.model_validate_json(spec_json)
        send.send(execute_probe(spec).model_dump_json())
    finally:
        send.close()


class ProcessProbeExecutor:
    def run(self, spec: ProbeSpec) -> ProbeOutcome:
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=worker_main, args=(send, spec.model_dump_json()))
        started = perf_counter_ns()
        process.start()
        send.close()
        process.join(spec.timeout_seconds)
        elapsed = _duration_ms(started)
        if process.is_alive():
            process.kill()
            process.join(5)
            receive.close()
            return self._failure(spec, FailureMode.TIMEOUT, "The probe reached its safety timeout.", elapsed)
        try:
            if receive.poll(0.2):
                return ProbeOutcome.model_validate_json(receive.recv())
        finally:
            receive.close()
        return self._failure(
            spec,
            FailureMode.WORKER_CRASH,
            "The isolated probe worker exited without an outcome.",
            elapsed,
        )

    @staticmethod
    def _failure(spec: ProbeSpec, mode: FailureMode, summary: str, elapsed: float) -> ProbeOutcome:
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.UNHEALTHY,
            checked_at=datetime.now(UTC),
            total_probe_duration_ms=elapsed,
            failure_stage=Stage.WORKER,
            failure_mode=mode,
            failure_summary=summary,
            failure_detail="ProcessTimeout" if mode == FailureMode.TIMEOUT else "WorkerProcessExit",
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=_datarepo_version(),
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )
