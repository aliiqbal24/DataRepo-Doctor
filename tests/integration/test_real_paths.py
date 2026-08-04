
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from datarepo_doctor.domain.canonical import result_sha256
from datarepo_doctor.domain.models import (
    AccessMethod,
    FailureMode,
    Health,
    ProbeSpec,
    SchemaField,
)
from datarepo_doctor.execution.engine import ProcessProbeExecutor
from datarepo_doctor.execution.queue import ProbeQueue
from datarepo_doctor.persistence.repository import DoctorRepository
from datarepo_doctor.registry import PROBES

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("spec", PROBES, ids=lambda spec: spec.check_id)
def test_real_access_path_materializes_and_validates_complete_result(spec):
    outcome = ProcessProbeExecutor().run(spec)
    assert outcome.health == Health.HEALTHY, outcome.model_dump()
    assert outcome.user_query_latency_ms is not None


def test_wrong_contracts_have_precise_failure_modes():
    executor = ProcessProbeExecutor()
    wrong_type = PROBES[0].expected_schema[0].model_copy(update={"type": "string"})
    schema = PROBES[0].model_copy(
        update={"expected_schema": (wrong_type,) + PROBES[0].expected_schema[1:]}
    )
    count = PROBES[0].model_copy(update={"expected_row_count": 999})
    fingerprint = PROBES[0].model_copy(update={"expected_sha256": "f" * 64})
    assert executor.run(schema).failure_mode == FailureMode.SCHEMA_MISMATCH
    assert executor.run(count).failure_mode == FailureMode.ROW_COUNT_MISMATCH
    assert executor.run(fingerprint).failure_mode == FailureMode.RESULT_FINGERPRINT_MISMATCH


def test_stopped_roapi_is_connection_error(monkeypatch):
    monkeypatch.setenv("DOCTOR_ROAPI_URL", "http://127.0.0.1:1")
    assert ProcessProbeExecutor().run(PROBES[3]).failure_mode == FailureMode.CONNECTION_ERROR


def test_stopped_postgres_is_connection_error(monkeypatch):
    monkeypatch.setenv("DOCTOR_POSTGRES_DSN", "postgresql://doctor_reader:unused@127.0.0.1:1/datarepo_demo")
    assert ProcessProbeExecutor().run(PROBES[2]).failure_mode == FailureMode.CONNECTION_ERROR


def test_invalid_object_credentials_are_unhealthy(monkeypatch):
    monkeypatch.setenv("DOCTOR_S3_SECRET_KEY", "invalid")
    outcome = ProcessProbeExecutor().run(PROBES[0])
    assert outcome.health == Health.UNHEALTHY
    assert outcome.failure_mode in {
        FailureMode.AUTHENTICATION_ERROR,
        FailureMode.AUTHORIZATION_ERROR,
        FailureMode.QUERY_EXECUTION_ERROR,
    }


def test_invalid_object_path_has_truthful_mode(monkeypatch):
    monkeypatch.setenv("DOCTOR_S3_BUCKET", "datarepo-demo-missing")
    outcome = ProcessProbeExecutor().run(PROBES[0])
    assert outcome.failure_mode in {FailureMode.SOURCE_NOT_FOUND, FailureMode.QUERY_EXECUTION_ERROR}


def _fault_spec(table: str, timeout: float = 3) -> ProbeSpec:
    provisional = ProbeSpec(
        check_id=f"fault-{table}",
        display_name=f"Fault {table}",
        description="Integration-only isolated worker fixture.",
        physical_source="test function table",
        catalog="tests.fault_catalog:FAULT_CATALOG",
        database="faults",
        table=table,
        access_method=AccessMethod.PYTHON_SDK,
        arguments={"lower": 1, "upper": 1},
        selected_columns=("id",),
        sort_columns=("id",),
        expected_schema=(SchemaField(name="id", type="int64"),),
        expected_row_count=1,
        expected_sha256="0" * 64,
        timeout_seconds=timeout,
        phase_offset_minutes=0,
        query_description="Integration-only bounded function arguments.",
    )
    digest = result_sha256([{"id": 1}], provisional)
    return provisional.model_copy(update={"expected_sha256": digest})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault", "mode", "timeout"),
    [
        ("hanging", FailureMode.TIMEOUT, 0.5),
        ("crashing", FailureMode.WORKER_CRASH, 3),
    ],
)
async def test_timeout_or_crash_does_not_strand_next_queued_check(tmp_path, fault, mode, timeout):
    bad = _fault_spec(fault, timeout=timeout)
    good = _fault_spec("succeeding")
    repo = DoctorRepository(f"sqlite:///{tmp_path / 'fault.db'}")
    repo.initialize((bad, good), datetime.now(UTC))
    queue = ProbeQueue((bad, good), repo)
    queue.start()
    await queue.enqueue(bad.check_id)
    await queue.enqueue(good.check_id)
    await queue.join()
    await queue.stop()
    assert repo.latest(bad.check_id).failure_mode == mode
    assert repo.latest(good.check_id).health == Health.HEALTHY
