from datetime import UTC, datetime, timedelta

import pytest

from datarepo_doctor.execution.queue import ProbeQueue
from datarepo_doctor.persistence.repository import DoctorRepository
from datarepo_doctor.registry import PROBES
from datarepo_doctor.scheduling import RecurringScheduler


@pytest.fixture
def repository(tmp_path):
    return DoctorRepository(f"sqlite:///{tmp_path / 'doctor.db'}")


def test_initial_stagger_and_override_survive_restart(repository):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repository.initialize(PROBES, now)
    schedules = repository.schedules()
    assert [schedules[p.check_id].next_run_at for p in PROBES] == [
        now + timedelta(minutes=offset) for offset in (0, 5, 10, 15)
    ]
    repository.update_schedule(PROBES[1].check_id, interval_minutes=120, now=now)
    restarted = DoctorRepository(str(repository.engine.url))
    restarted.initialize(PROBES, now + timedelta(days=1))
    assert restarted.schedule(PROBES[1].check_id).interval_minutes == 120


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
