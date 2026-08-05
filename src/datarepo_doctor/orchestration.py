"""One FIFO worker plus independently persisted recurring schedules."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from datarepo_doctor.models import FailureMode, ProbeOutcome, ProbeSpec
from datarepo_doctor.runner import ProcessProbeExecutor
from datarepo_doctor.storage import DoctorRepository


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    IDLE = "idle"


@dataclass(frozen=True)
class JobState:
    check_id: str
    status: JobStatus
    enqueued_at: datetime | None = None
    source: str | None = None


class Executor(Protocol):
    def run(self, spec: ProbeSpec) -> ProbeOutcome: ...


class ProbeQueue:
    def __init__(
        self,
        probes: tuple[ProbeSpec, ...],
        repository: DoctorRepository,
        executor: Executor | None = None,
    ) -> None:
        self._probes = {probe.check_id: probe for probe in probes}
        self._repository = repository
        self._executor = executor or ProcessProbeExecutor()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._states: dict[str, JobState] = {}
        self._worker: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._work(), name="probe-fifo-worker")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def enqueue(self, check_id: str, source: str = "manual") -> JobState:
        if check_id not in self._probes:
            raise KeyError(check_id)
        current = self._states.get(check_id)
        if current and current.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return current
        state = JobState(check_id, JobStatus.QUEUED, datetime.now(UTC), source)
        self._states[check_id] = state
        await self._queue.put(check_id)
        return state

    def state(self, check_id: str) -> JobState:
        return self._states.get(check_id, JobState(check_id, JobStatus.IDLE))

    def worker_state(self) -> dict[str, object]:
        running = next(
            (check_id for check_id, state in self._states.items() if state.status == JobStatus.RUNNING),
            None,
        )
        return {"running_check_id": running, "queued_count": self._queue.qsize(), "concurrency": 1}

    async def join(self) -> None:
        await self._queue.join()

    async def _work(self) -> None:
        while True:
            check_id = await self._queue.get()
            queued = self._states[check_id]
            self._states[check_id] = JobState(
                check_id,
                JobStatus.RUNNING,
                queued.enqueued_at,
                queued.source,
            )
            try:
                try:
                    outcome = await asyncio.to_thread(self._executor.run, self._probes[check_id])
                except BaseException:
                    outcome = ProcessProbeExecutor._failure(
                        self._probes[check_id],
                        FailureMode.WORKER_CRASH,
                        "The probe executor exited without an outcome.",
                    )
                self._repository.save_outcome(outcome)
            finally:
                self._states[check_id] = JobState(check_id, JobStatus.IDLE)
                self._queue.task_done()


class RecurringScheduler:
    def __init__(
        self,
        probes: tuple[ProbeSpec, ...],
        repository: DoctorRepository,
        queue: ProbeQueue,
    ) -> None:
        self._probes = probes
        self._repository = repository
        self._queue = queue
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="recurring-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def enqueue_due(self, now: datetime | None = None) -> list[str]:
        timestamp = now or datetime.now(UTC)
        schedules = self._repository.schedules()
        for probe in self._probes:
            schedule = schedules[probe.check_id]
            if schedule.enabled and schedule.next_run_at <= timestamp:
                await self._queue.enqueue(probe.check_id, source="scheduled")
                self._repository.advance_schedule(probe.check_id, timestamp)
                return [probe.check_id]
        return []

    async def _loop(self) -> None:
        while True:
            await self.enqueue_due()
            await asyncio.sleep(1)
