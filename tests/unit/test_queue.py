import time

import pytest

from datarepo_doctor.execution.queue import JobStatus, ProbeQueue
from datarepo_doctor.persistence.repository import DoctorRepository
from datarepo_doctor.registry import PROBES
from tests.unit.conftest import healthy_outcome


class RecordingExecutor:
    def __init__(self):
        self.events = []

    def run(self, spec):
        self.events.append(("start", spec.check_id))
        time.sleep(0.02)
        self.events.append(("end", spec.check_id))
        return healthy_outcome(spec)


class FirstCrashExecutor(RecordingExecutor):
    def run(self, spec):
        if not self.events:
            self.events.append(("crash", spec.check_id))
            raise RuntimeError("secret traceback")
        return super().run(spec)


@pytest.mark.asyncio
async def test_queue_deduplicates_and_executes_globally_sequential(tmp_path):
    repo = DoctorRepository(f"sqlite:///{tmp_path / 'q.db'}")
    repo.initialize(PROBES)
    executor = RecordingExecutor()
    queue = ProbeQueue(PROBES, repo, executor)
    queue.start()
    first = await queue.enqueue(PROBES[0].check_id)
    duplicate = await queue.enqueue(PROBES[0].check_id)
    await queue.enqueue(PROBES[1].check_id)
    assert duplicate.enqueued_at == first.enqueued_at
    await queue.join()
    await queue.stop()
    assert executor.events == [
        ("start", PROBES[0].check_id),
        ("end", PROBES[0].check_id),
        ("start", PROBES[1].check_id),
        ("end", PROBES[1].check_id),
    ]
    assert queue.state(PROBES[0].check_id).status == JobStatus.IDLE


@pytest.mark.asyncio
async def test_executor_crash_does_not_strand_next_job(tmp_path):
    repo = DoctorRepository(f"sqlite:///{tmp_path / 'q.db'}")
    repo.initialize(PROBES)
    executor = FirstCrashExecutor()
    queue = ProbeQueue(PROBES, repo, executor)
    queue.start()
    await queue.enqueue(PROBES[0].check_id)
    await queue.enqueue(PROBES[1].check_id)
    await queue.join()
    await queue.stop()
    assert repo.latest(PROBES[0].check_id).failure_mode == "worker_crash"
    assert repo.latest(PROBES[1].check_id).health == "healthy"
