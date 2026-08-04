from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from datarepo_doctor.domain.models import ProbeSpec
from datarepo_doctor.execution.queue import ProbeQueue
from datarepo_doctor.persistence.repository import DoctorRepository


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
        enqueued: list[str] = []
        for probe in self._probes:
            schedule = schedules[probe.check_id]
            if schedule.enabled and schedule.next_run_at <= timestamp:
                await self._queue.enqueue(probe.check_id, source="scheduled")
                self._repository.advance_schedule(probe.check_id, timestamp)
                enqueued.append(probe.check_id)
                # Restore overdue schedules gradually. The next loop handles the
                # next registry item, avoiding a restart thundering herd.
                break
        return enqueued

    async def _loop(self) -> None:
        while True:
            await self.enqueue_due()
            await asyncio.sleep(1)
