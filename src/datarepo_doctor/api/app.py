from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from datarepo_doctor.config import Settings
from datarepo_doctor.domain.models import Health, ProbeOutcome, ProbeSpec
from datarepo_doctor.execution.queue import ProbeQueue
from datarepo_doctor.persistence.repository import DoctorRepository, ScheduleRecord
from datarepo_doctor.registry import PROBES, get_probe
from datarepo_doctor.scheduling import RecurringScheduler


class SchedulePatch(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)


def _safe_spec(spec: ProbeSpec, *, detail: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "check_id": spec.check_id,
        "display_name": spec.display_name,
        "description": spec.description,
        "physical_source": spec.physical_source,
        "access_method": spec.access_method.value,
        "catalog": spec.catalog.split(":", 1)[0],
        "database": spec.database,
        "table": spec.table,
        "environment": spec.environment,
        "credential_profile": spec.credential_profile,
        "query_description": spec.query_description,
        "spec_version": spec.spec_version,
        "spec_hash": spec.spec_hash,
    }
    if detail:
        result["validation_contract"] = {
            "selected_columns": list(spec.selected_columns),
            "sort_columns": list(spec.sort_columns),
            "expected_schema": [field.model_dump() for field in spec.expected_schema],
            "expected_row_count": spec.expected_row_count,
            "expected_sha256": spec.expected_sha256,
            "timeout_seconds": spec.timeout_seconds,
        }
    return result


def _schedule_json(schedule: ScheduleRecord) -> dict[str, Any]:
    value = asdict(schedule)
    value["next_run_at"] = schedule.next_run_at.isoformat()
    value["updated_at"] = schedule.updated_at.isoformat()
    return value


def _outcome_json(outcome: ProbeOutcome | None) -> dict[str, Any] | None:
    return None if outcome is None else outcome.model_dump(mode="json")


def create_app(
    settings: Settings | None = None,
    repository: DoctorRepository | None = None,
    queue: ProbeQueue | None = None,
) -> FastAPI:
    config = settings or Settings()
    repo = repository or DoctorRepository(config.database_url)
    probe_queue = queue or ProbeQueue(PROBES, repo)
    scheduler = RecurringScheduler(PROBES, repo, probe_queue)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo.initialize(PROBES)
        probe_queue.start()
        if config.schedules_enabled:
            await scheduler.enqueue_due()
            scheduler.start()
        app.state.repository = repo
        app.state.queue = probe_queue
        yield
        if config.schedules_enabled:
            await scheduler.stop()
        await probe_queue.stop()

    app = FastAPI(
        title="DataRepo Doctor",
        version="0.1.0",
        description="Bounded DataRepo synthetic retrieval monitor",
        lifespan=lifespan,
    )

    @app.get("/api/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/checks")
    def checks() -> list[dict[str, Any]]:
        latest = repo.latest_all()
        schedules = repo.schedules()
        return [
            {
                **_safe_spec(spec),
                "latest_outcome": _outcome_json(latest.get(spec.check_id)),
                "schedule": _schedule_json(schedules[spec.check_id]),
                "job": asdict(probe_queue.state(spec.check_id)),
            }
            for spec in PROBES
        ]

    @app.get("/api/checks/{check_id}")
    def check_detail(check_id: str) -> dict[str, Any]:
        try:
            spec = get_probe(check_id)
            schedule = repo.schedule(check_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Check not found") from exc
        return {
            **_safe_spec(spec, detail=True),
            "latest_outcome": _outcome_json(repo.latest(check_id)),
            "schedule": _schedule_json(schedule),
            "job": asdict(probe_queue.state(check_id)),
        }

    @app.post("/api/checks/{check_id}/run", status_code=status.HTTP_202_ACCEPTED)
    async def run_check(check_id: str, response: Response) -> dict[str, Any]:
        try:
            state = await probe_queue.enqueue(check_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Check not found") from exc
        response.status_code = status.HTTP_202_ACCEPTED
        return asdict(state)

    @app.patch("/api/checks/{check_id}/schedule")
    def patch_schedule(check_id: str, patch: SchedulePatch) -> dict[str, Any]:
        if patch.enabled is None and patch.interval_minutes is None:
            raise HTTPException(status_code=422, detail="No schedule change supplied")
        try:
            updated = repo.update_schedule(
                check_id,
                enabled=patch.enabled,
                interval_minutes=patch.interval_minutes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Check not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _schedule_json(updated)

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        latest = repo.latest_all()
        healthy = sum(outcome.health == Health.HEALTHY for outcome in latest.values())
        unhealthy = sum(outcome.health == Health.UNHEALTHY for outcome in latest.values())
        return {
            "healthy": healthy,
            "unhealthy": unhealthy,
            "not_yet_checked": len(PROBES) - healthy - unhealthy,
            "total": len(PROBES),
            "worker": probe_queue.worker_state(),
        }

    dist = Path(os.getenv("DOCTOR_WEB_DIST", "/app/web/dist"))
    if not dist.is_dir():
        dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend(full_path: str) -> FileResponse:
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
