from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from datarepo_doctor.domain.models import ProbeOutcome, ProbeSpec

from .models import Base, CheckScheduleRow, LatestProbeRunRow


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class ScheduleRecord:
    check_id: str
    interval_minutes: int
    phase_offset_minutes: int
    next_run_at: datetime
    enabled: bool
    updated_at: datetime


class DoctorRepository:
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self, probes: tuple[ProbeSpec, ...], now: datetime | None = None) -> None:
        Base.metadata.create_all(self.engine)
        baseline = _utc(now or datetime.now(UTC)).replace(second=0, microsecond=0)
        with self.sessions.begin() as session:
            configured_ids = {probe.check_id for probe in probes}
            session.execute(delete(CheckScheduleRow).where(CheckScheduleRow.check_id.not_in(configured_ids)))
            session.execute(delete(LatestProbeRunRow).where(LatestProbeRunRow.check_id.not_in(configured_ids)))
            existing = set(session.scalars(select(CheckScheduleRow.check_id)))
            for probe in probes:
                if probe.check_id not in existing:
                    session.add(
                        CheckScheduleRow(
                            check_id=probe.check_id,
                            interval_minutes=probe.default_interval_minutes,
                            phase_offset_minutes=probe.phase_offset_minutes,
                            next_run_at=baseline + timedelta(minutes=probe.phase_offset_minutes),
                            enabled=True,
                            updated_at=baseline,
                        )
                    )

    def schedules(self) -> dict[str, ScheduleRecord]:
        with self.sessions() as session:
            rows = session.scalars(select(CheckScheduleRow)).all()
            return {row.check_id: self._schedule(row) for row in rows}

    def schedule(self, check_id: str) -> ScheduleRecord:
        with self.sessions() as session:
            row = session.get(CheckScheduleRow, check_id)
            if row is None:
                raise KeyError(check_id)
            return self._schedule(row)

    def update_schedule(
        self,
        check_id: str,
        *,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
        now: datetime | None = None,
    ) -> ScheduleRecord:
        timestamp = _utc(now or datetime.now(UTC))
        with self.sessions.begin() as session:
            row = session.get(CheckScheduleRow, check_id)
            if row is None:
                raise KeyError(check_id)
            was_enabled = row.enabled
            if enabled is not None:
                row.enabled = enabled
            if interval_minutes is not None:
                if not 5 <= interval_minutes <= 10080:
                    raise ValueError("interval must be between 5 and 10080 minutes")
                row.interval_minutes = interval_minutes
                row.next_run_at = timestamp + timedelta(minutes=interval_minutes)
            elif enabled and not was_enabled:
                row.next_run_at = timestamp
            row.updated_at = timestamp
            session.flush()
            return self._schedule(row)

    def advance_schedule(self, check_id: str, now: datetime | None = None) -> ScheduleRecord:
        timestamp = _utc(now or datetime.now(UTC))
        with self.sessions.begin() as session:
            row = session.get(CheckScheduleRow, check_id)
            if row is None:
                raise KeyError(check_id)
            next_run = _utc(row.next_run_at)
            interval = timedelta(minutes=row.interval_minutes)
            while next_run <= timestamp:
                next_run += interval
            row.next_run_at = next_run
            row.updated_at = timestamp
            session.flush()
            return self._schedule(row)

    def save_outcome(self, outcome: ProbeOutcome) -> None:
        with self.sessions.begin() as session:
            row = session.get(LatestProbeRunRow, outcome.check_id)
            if row is None:
                row = LatestProbeRunRow(
                    check_id=outcome.check_id,
                    outcome_json=outcome.model_dump_json(),
                    checked_at=outcome.checked_at,
                )
                session.add(row)
            else:
                row.outcome_json = outcome.model_dump_json()
                row.checked_at = outcome.checked_at

    def latest(self, check_id: str) -> ProbeOutcome | None:
        with self.sessions() as session:
            row = session.get(LatestProbeRunRow, check_id)
            return None if row is None else ProbeOutcome.model_validate_json(row.outcome_json)

    def latest_all(self) -> dict[str, ProbeOutcome]:
        with self.sessions() as session:
            rows = session.scalars(select(LatestProbeRunRow)).all()
            return {row.check_id: ProbeOutcome.model_validate_json(row.outcome_json) for row in rows}

    @staticmethod
    def _schedule(row: CheckScheduleRow) -> ScheduleRecord:
        return ScheduleRecord(
            check_id=row.check_id,
            interval_minutes=row.interval_minutes,
            phase_offset_minutes=row.phase_offset_minutes,
            next_run_at=_utc(row.next_run_at),
            enabled=row.enabled,
            updated_at=_utc(row.updated_at),
        )
