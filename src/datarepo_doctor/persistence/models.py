from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CheckScheduleRow(Base):
    __tablename__ = "check_schedule"
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LatestProbeRunRow(Base):
    __tablename__ = "latest_probe_run"
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    outcome_json: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
