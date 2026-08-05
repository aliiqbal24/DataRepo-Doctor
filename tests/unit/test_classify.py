import socket

import httpx
import pytest

from datarepo_doctor.models import FailureMode, Stage
from datarepo_doctor.runner import (
    StageError,
    classify_exception,
    safe_exception_detail,
    sanitize_error_message,
)
from datarepo_doctor.validation import FingerprintMismatch, SchemaMismatch


@pytest.mark.parametrize(
    ("exc", "mode"),
    [
        (SchemaMismatch(), FailureMode.SCHEMA_MISMATCH),
        (FingerprintMismatch(), FailureMode.RESULT_FINGERPRINT_MISMATCH),
        (socket.gaierror(), FailureMode.DNS_ERROR),
        (FileNotFoundError(), FailureMode.SOURCE_NOT_FOUND),
        (ConnectionRefusedError(), FailureMode.CONNECTION_ERROR),
    ],
)
def test_typed_exception_classification(exc, mode):
    wrapped = StageError(Stage.QUERY, FailureMode.QUERY_EXECUTION_ERROR, exc)
    assert classify_exception(wrapped)[1] == mode


def test_http_status_classification():
    request = httpx.Request("GET", "http://safe.invalid")
    response = httpx.Response(403, request=request)
    exc = httpx.HTTPStatusError("ignored", request=request, response=response)
    stage, mode, summary = classify_exception(StageError(Stage.QUERY, FailureMode.HTTP_ERROR, exc))
    assert (stage, mode) == (Stage.QUERY, FailureMode.AUTHORIZATION_ERROR)
    assert "safe.invalid" not in summary


def test_error_detail_scrubs_urls_secrets_literals_and_long_tokens():
    message = (
        "request https://internal.example/query?token=hunter2 "
        "password=unsafe value='returned-row' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )
    safe = sanitize_error_message(message)
    assert "internal.example" not in safe
    assert "hunter2" not in safe
    assert "unsafe" not in safe
    assert "returned-row" not in safe
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in safe


def test_unknown_exception_exposes_type_not_unstructured_message():
    detail = safe_exception_detail(RuntimeError("password=unsafe returned-row"))
    assert detail == "RuntimeError"
