from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from time import perf_counter_ns

from datarepo_doctor import __version__
from datarepo_doctor.domain.canonical import validate_result
from datarepo_doctor.domain.models import (
    AccessMethod,
    FailureMode,
    Health,
    PhaseTiming,
    ProbeOutcome,
    ProbeSpec,
    Stage,
)

from .classify import classify_exception
from .context import execution_stage


def _duration_ms(start: int) -> float:
    return round((perf_counter_ns() - start) / 1_000_000, 3)


def execute_probe(spec: ProbeSpec) -> ProbeOutcome:
    started = perf_counter_ns()
    datarepo_version = importlib.metadata.version("data-repository")
    try:
        # Keep third-party DataRepo imports inside the isolated child.
        from datarepo_doctor.adapters.python_datarepo import PythonDataRepoAdapter
        from datarepo_doctor.adapters.roapi_http import RoapiHttpAdapter

        adapter = (
            PythonDataRepoAdapter() if spec.access_method == AccessMethod.PYTHON_SDK else RoapiHttpAdapter()
        )
        result = adapter.execute(spec)
        validation_started = perf_counter_ns()
        with execution_stage(Stage.VALIDATION, FailureMode.UNKNOWN):
            validate_result(result.rows, spec)
        validation_done = perf_counter_ns()
        # Discard materialized values before constructing the boundary outcome.
        # AdapterResult is frozen, but the short-lived list can be cleared in place.
        result.rows.clear()
        phases = result.phases + (
            PhaseTiming(
                name="validation",
                duration_ms=round((validation_done - validation_started) / 1_000_000, 3),
            ),
        )
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.HEALTHY,
            checked_at=datetime.now(UTC),
            user_query_latency_ms=result.user_query_latency_ms,
            phase_timings=phases,
            total_probe_duration_ms=_duration_ms(started),
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=datarepo_version,
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )
    except BaseException as exc:
        stage, mode, summary = classify_exception(exc)
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.UNHEALTHY,
            checked_at=datetime.now(UTC),
            total_probe_duration_ms=_duration_ms(started),
            failure_stage=stage,
            failure_mode=mode,
            failure_summary=summary,
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=datarepo_version,
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )


def worker_main(send: Connection, spec_json: str) -> None:
    try:
        spec = ProbeSpec.model_validate_json(spec_json)
        outcome = execute_probe(spec)
        send.send(outcome.model_dump_json())
    finally:
        send.close()
