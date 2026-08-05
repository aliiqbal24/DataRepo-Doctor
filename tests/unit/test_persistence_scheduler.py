import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from datarepo_doctor.checks import PROBES
from datarepo_doctor.orchestration import ProbeQueue, RecurringScheduler
from datarepo_doctor.storage import DoctorRepository
from tests.unit.conftest import healthy_outcome


@pytest.fixture
def repository(tmp_path):
    return DoctorRepository(str(tmp_path / "doctor.db"))


def test_initial_stagger_and_override_survive_restart(repository):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repository.initialize(PROBES, now)
    schedules = repository.schedules()
    assert [schedules[p.check_id].next_run_at for p in PROBES] == [
        now + timedelta(minutes=offset) for offset in (0, 5, 10, 15)
    ]
    repository.update_schedule(PROBES[1].check_id, interval_minutes=120, now=now)
    restarted = DoctorRepository(repository.database_path)
    restarted.initialize(PROBES, now + timedelta(days=1))
    assert restarted.schedule(PROBES[1].check_id).interval_minutes == 120


def test_removed_registry_checks_are_pruned_on_restart(repository):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repository.initialize(PROBES, now)

    repository.initialize(PROBES[1:], now + timedelta(minutes=1))

    assert PROBES[0].check_id not in repository.schedules()


def test_outcomes_from_the_previous_model_remain_readable(repository):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    probe = PROBES[0]
    repository.initialize(PROBES, now)
    old = healthy_outcome(probe).model_dump(mode="json")
    old.update(
        health="unhealthy",
        user_query_latency_ms=None,
        failure_stage="validation",
        failure_mode="schema_mismatch",
        failure_summary="Result schema did not match the contract.",
        failure_detail="SchemaMismatch",
        phase_timings=[],
        total_probe_duration_ms=12.3,
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            "INSERT INTO latest_probe_run (check_id, outcome_json, checked_at) VALUES (?, ?, ?)",
            (probe.check_id, json.dumps(old), now.isoformat()),
        )

    outcome = repository.latest(probe.check_id)

    assert outcome is not None
    assert outcome.failure_mode == "validation_error"


@pytest.mark.asyncio
async def test_manual_run_does_not_change_cadence(repository):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repository.initialize(PROBES, now)
    queue = ProbeQueue(PROBES, repository)
    before = repository.schedule(PROBES[0].check_id).next_run_at
    await queue.enqueue(PROBES[0].check_id, source="manual")
    assert repository.schedule(PROBES[0].check_id).next_run_at == before


@pytest.mark.asyncio
async def test_restart_restores_only_one_overdue_per_tick(repository):
    now = datetime(2026, 1, 2, tzinfo=UTC)
    repository.initialize(PROBES, now - timedelta(days=1))
    queue = ProbeQueue(PROBES, repository)
    scheduler = RecurringScheduler(PROBES, repository, queue)
    assert await scheduler.enqueue_due(now) == [PROBES[0].check_id]
    assert await scheduler.enqueue_due(now) == [PROBES[1].check_id]
