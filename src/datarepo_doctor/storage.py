"""Persist schedules and the latest outcomes with Python's built-in SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from datarepo_doctor.models import FailureMode, ProbeOutcome, ProbeSpec

_OLD_CONNECTION_MODES = {"dns_error", "connection_error"}
_OLD_VALIDATION_MODES = {
    "schema_mismatch",
    "row_count_mismatch",
    "result_fingerprint_mismatch",
}
_CURRENT_FAILURE_MODES = {mode.value for mode in FailureMode}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat()


def _load_outcome(payload: str) -> ProbeOutcome:
    """Read outcomes saved before the monitoring model was simplified."""

    data = json.loads(payload)
    for removed_field in ("phase_timings", "total_probe_duration_ms", "failure_stage"):
        data.pop(removed_field, None)
    old_mode = data.get("failure_mode")
    if old_mode and old_mode not in _CURRENT_FAILURE_MODES:
        if old_mode in _OLD_CONNECTION_MODES:
            data["failure_mode"] = FailureMode.CONNECTION_ERROR
        elif old_mode in _OLD_VALIDATION_MODES:
            data["failure_mode"] = FailureMode.VALIDATION_ERROR
        else:
            data["failure_mode"] = FailureMode.QUERY_ERROR
    return ProbeOutcome.model_validate(data)


@dataclass(frozen=True)
class ScheduleRecord:
    check_id: str
    interval_minutes: int
    phase_offset_minutes: int
    next_run_at: datetime
    enabled: bool
    updated_at: datetime


class DoctorRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self, probes: tuple[ProbeSpec, ...], now: datetime | None = None) -> None:
        baseline = _utc(now or datetime.now(UTC)).replace(second=0, microsecond=0)
        configured_ids = tuple(probe.check_id for probe in probes)
        placeholders = ",".join("?" for _ in configured_ids)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS check_schedule (
                    check_id TEXT PRIMARY KEY,
                    interval_minutes INTEGER NOT NULL,
                    phase_offset_minutes INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS latest_probe_run (
                    check_id TEXT PRIMARY KEY,
                    outcome_json TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                """
            )
            if configured_ids:
                connection.execute(
                    f"DELETE FROM check_schedule WHERE check_id NOT IN ({placeholders})",  # noqa: S608
                    configured_ids,
                )
                connection.execute(
                    f"DELETE FROM latest_probe_run WHERE check_id NOT IN ({placeholders})",  # noqa: S608
                    configured_ids,
                )
            else:
                connection.execute("DELETE FROM check_schedule")
                connection.execute("DELETE FROM latest_probe_run")
            for probe in probes:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO check_schedule
                        (check_id, interval_minutes, phase_offset_minutes, next_run_at, enabled, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (
                        probe.check_id,
                        probe.default_interval_minutes,
                        probe.phase_offset_minutes,
                        _timestamp(baseline + timedelta(minutes=probe.phase_offset_minutes)),
                        _timestamp(baseline),
                    ),
                )

    def schedules(self) -> dict[str, ScheduleRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM check_schedule").fetchall()
        return {str(row["check_id"]): self._schedule(row) for row in rows}

    def schedule(self, check_id: str) -> ScheduleRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM check_schedule WHERE check_id = ?", (check_id,)
            ).fetchone()
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
        if interval_minutes is not None and not 5 <= interval_minutes <= 10080:
            raise ValueError("interval must be between 5 and 10080 minutes")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM check_schedule WHERE check_id = ?", (check_id,)
            ).fetchone()
            if row is None:
                raise KeyError(check_id)
            next_enabled = bool(row["enabled"]) if enabled is None else enabled
            next_interval = int(row["interval_minutes"]) if interval_minutes is None else interval_minutes
            next_run = datetime.fromisoformat(str(row["next_run_at"]))
            if interval_minutes is not None:
                next_run = timestamp + timedelta(minutes=interval_minutes)
            elif enabled and not bool(row["enabled"]):
                next_run = timestamp
            connection.execute(
                """
                UPDATE check_schedule
                   SET enabled = ?, interval_minutes = ?, next_run_at = ?, updated_at = ?
                 WHERE check_id = ?
                """,
                (
                    int(next_enabled),
                    next_interval,
                    _timestamp(next_run),
                    _timestamp(timestamp),
                    check_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM check_schedule WHERE check_id = ?", (check_id,)
            ).fetchone()
        assert updated is not None
        return self._schedule(updated)

    def advance_schedule(self, check_id: str, now: datetime | None = None) -> ScheduleRecord:
        timestamp = _utc(now or datetime.now(UTC))
        current = self.schedule(check_id)
        next_run = current.next_run_at
        interval = timedelta(minutes=current.interval_minutes)
        while next_run <= timestamp:
            next_run += interval
        with self._connect() as connection:
            connection.execute(
                "UPDATE check_schedule SET next_run_at = ?, updated_at = ? WHERE check_id = ?",
                (_timestamp(next_run), _timestamp(timestamp), check_id),
            )
        return self.schedule(check_id)

    def save_outcome(self, outcome: ProbeOutcome) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO latest_probe_run (check_id, outcome_json, checked_at)
                VALUES (?, ?, ?)
                ON CONFLICT(check_id) DO UPDATE SET
                    outcome_json = excluded.outcome_json,
                    checked_at = excluded.checked_at
                """,
                (outcome.check_id, outcome.model_dump_json(), _timestamp(outcome.checked_at)),
            )

    def latest(self, check_id: str) -> ProbeOutcome | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT outcome_json FROM latest_probe_run WHERE check_id = ?", (check_id,)
            ).fetchone()
        return None if row is None else _load_outcome(str(row["outcome_json"]))

    def latest_all(self) -> dict[str, ProbeOutcome]:
        with self._connect() as connection:
            rows = connection.execute("SELECT check_id, outcome_json FROM latest_probe_run").fetchall()
        return {
            str(row["check_id"]): _load_outcome(str(row["outcome_json"]))
            for row in rows
        }

    @staticmethod
    def _schedule(row: sqlite3.Row) -> ScheduleRecord:
        return ScheduleRecord(
            check_id=str(row["check_id"]),
            interval_minutes=int(row["interval_minutes"]),
            phase_offset_minutes=int(row["phase_offset_minutes"]),
            next_run_at=_utc(datetime.fromisoformat(str(row["next_run_at"]))),
            enabled=bool(row["enabled"]),
            updated_at=_utc(datetime.fromisoformat(str(row["updated_at"]))),
        )
