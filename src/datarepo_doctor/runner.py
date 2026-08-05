"""One isolated probe run with safe errors, validation, and a hard timeout."""

from __future__ import annotations

import importlib.metadata
import multiprocessing
import re
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from multiprocessing.connection import Connection

import httpx

from datarepo_doctor import __version__
from datarepo_doctor.models import FailureMode, Health, ProbeOutcome, ProbeSpec
from datarepo_doctor.validation import ProbeError, validate_result


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


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

    cause = exc
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


def classify_exception(exc: BaseException) -> tuple[FailureMode, str]:
    """Collapse failures into the five categories the dashboard acts on."""

    for cause in _chain(exc):
        if isinstance(cause, ProbeError):
            return FailureMode.VALIDATION_ERROR, cause.safe_summary
        if isinstance(
            cause,
            (
                socket.gaierror,
                httpx.ConnectError,
                httpx.TimeoutException,
                ConnectionRefusedError,
                ConnectionResetError,
                TimeoutError,
            ),
        ):
            return FailureMode.CONNECTION_ERROR, "The configured service could not be reached."
        module_name = cause.__class__.__module__
        class_name = cause.__class__.__name__
        if module_name.startswith("psycopg") and class_name in {"OperationalError", "ConnectionTimeout"}:
            return FailureMode.CONNECTION_ERROR, "The configured service could not be reached."
        if module_name.startswith("botocore") and class_name in {
            "ConnectTimeoutError",
            "EndpointConnectionError",
            "ReadTimeoutError",
        }:
            return FailureMode.CONNECTION_ERROR, "The configured service could not be reached."

    return FailureMode.QUERY_ERROR, "The bounded retrieval failed."


def _datarepo_version() -> str:
    try:
        return importlib.metadata.version("data-repository")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def execute_probe(spec: ProbeSpec) -> ProbeOutcome:
    try:
        # Retrieval imports stay inside the isolated process. This also avoids
        # importing DataRepo's heavy dependencies in the FastAPI parent.
        from datarepo_doctor.retrieval import retrieve

        result = retrieve(spec)
        validate_result(result.rows, spec)
        display_rows = tuple(dict(row) for row in result.rows) if spec.display_result_rows else ()
        result.rows.clear()
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.HEALTHY,
            checked_at=datetime.now(UTC),
            user_query_latency_ms=result.user_query_latency_ms,
            result_rows=display_rows,
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=_datarepo_version(),
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )
    except BaseException as exc:
        mode, summary = classify_exception(exc)
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.UNHEALTHY,
            checked_at=datetime.now(UTC),
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
        process.start()
        send.close()
        process.join(spec.timeout_seconds)
        if process.is_alive():
            process.kill()
            process.join(5)
            receive.close()
            return self._failure(spec, FailureMode.TIMEOUT, "The probe reached its safety timeout.")
        try:
            if receive.poll(0.2):
                return ProbeOutcome.model_validate_json(receive.recv())
        finally:
            receive.close()
        return self._failure(
            spec,
            FailureMode.WORKER_CRASH,
            "The isolated probe worker exited without an outcome.",
        )

    @staticmethod
    def _failure(spec: ProbeSpec, mode: FailureMode, summary: str) -> ProbeOutcome:
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.UNHEALTHY,
            checked_at=datetime.now(UTC),
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
