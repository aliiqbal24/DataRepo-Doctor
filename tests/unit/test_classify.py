import socket

import httpx
import pytest

from datarepo_doctor.domain.errors import FingerprintMismatch, SchemaMismatch
from datarepo_doctor.domain.models import FailureMode, Stage
from datarepo_doctor.execution.classify import classify_exception
from datarepo_doctor.execution.context import StageError


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
