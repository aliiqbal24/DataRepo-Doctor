from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from datarepo_doctor.checks import PROBES
from datarepo_doctor.config import Settings
from datarepo_doctor.models import ProbeOutcome, ProbeSpec
from datarepo_doctor.orchestration import ProbeQueue, RecurringScheduler
from datarepo_doctor.retrieval import query_code
from datarepo_doctor.storage import DoctorRepository, ScheduleRecord


class SchedulePatch(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)


def _safe_spec(spec: ProbeSpec) -> dict[str, Any]:
    """Return the complete UI contract without filters, arguments, or secrets."""

    return {
        "check_id": spec.check_id,
        "display_name": spec.display_name,
        "description": spec.description,
        "physical_source": spec.physical_source,
        "source_owner": spec.source_owner,
        "source_uri": spec.source_uri,
        "source_version": spec.source_version,
        "source_license": spec.source_license,
        "source_documentation_url": spec.source_documentation_url,
        "access_method": spec.access_method.value,
        "catalog": spec.catalog.split(":", 1)[0],
        "database": spec.database,
        "table": spec.table,
        "environment": spec.environment,
        "credential_profile": spec.credential_profile,
        "query_description": spec.query_description,
        "query_code": query_code(spec),
        "displays_result_rows": spec.display_result_rows,
        "spec_version": spec.spec_version,
        "spec_hash": spec.spec_hash,
    }


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
        version="0.2.0",
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

    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app
