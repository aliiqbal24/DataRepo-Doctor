from __future__ import annotations

import socket
from collections.abc import Iterator

import httpx

from datarepo_doctor.domain.errors import ProbeError
from datarepo_doctor.domain.models import FailureMode, Stage

from .context import StageError


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_exception(exc: BaseException) -> tuple[Stage, FailureMode, str]:
    stage = Stage.WORKER
    fallback = FailureMode.UNKNOWN
    root: BaseException = exc
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

        # Botocore exposes structured error codes. Import lazily so unit-only
        # installations do not require boto3.
        if cause.__class__.__module__.startswith("botocore") and hasattr(cause, "response"):
            code = str(getattr(cause, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"}:
                return stage, FailureMode.AUTHENTICATION_ERROR, "Object credentials were rejected."
            if code in {"AccessDenied", "Forbidden"}:
                return stage, FailureMode.AUTHORIZATION_ERROR, "Object access was denied."
            if code in {"NoSuchBucket", "NoSuchKey", "404"}:
                return stage, FailureMode.SOURCE_NOT_FOUND, "The configured object source was not found."

        # psycopg's SQLSTATE classes are typed even when psycopg is optional here.
        module_name = cause.__class__.__module__
        class_name = cause.__class__.__name__
        if module_name.startswith("psycopg"):
            if class_name in {"InvalidPassword", "InvalidAuthorizationSpecification"}:
                return stage, FailureMode.AUTHENTICATION_ERROR, "PostgreSQL credentials were rejected."
            if class_name in {"InsufficientPrivilege"}:
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
