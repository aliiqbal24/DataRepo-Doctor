from __future__ import annotations

import importlib.metadata
import multiprocessing
from datetime import UTC, datetime
from time import perf_counter_ns

from datarepo_doctor import __version__
from datarepo_doctor.domain.models import FailureMode, Health, ProbeOutcome, ProbeSpec, Stage

from .worker import worker_main


class ProcessProbeExecutor:
    """Runs exactly one probe in a fresh spawn child and returns only its outcome."""

    def run(self, spec: ProbeSpec) -> ProbeOutcome:
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=worker_main, args=(send, spec.model_dump_json()))
        started = perf_counter_ns()
        process.start()
        send.close()
        process.join(spec.timeout_seconds)
        elapsed = round((perf_counter_ns() - started) / 1_000_000, 3)
        if process.is_alive():
            process.kill()
            process.join(5)
            receive.close()
            return self._failure(spec, FailureMode.TIMEOUT, "The probe reached its safety timeout.", elapsed)
        try:
            if receive.poll(0.2):
                return ProbeOutcome.model_validate_json(receive.recv())
        finally:
            receive.close()
        return self._failure(
            spec, FailureMode.WORKER_CRASH, "The isolated probe worker exited without an outcome.", elapsed
        )

    @staticmethod
    def _failure(spec: ProbeSpec, mode: FailureMode, summary: str, elapsed: float) -> ProbeOutcome:
        try:
            datarepo_version = importlib.metadata.version("data-repository")
        except Exception:
            datarepo_version = "unknown"
        return ProbeOutcome(
            check_id=spec.check_id,
            health=Health.UNHEALTHY,
            checked_at=datetime.now(UTC),
            total_probe_duration_ms=elapsed,
            failure_stage=Stage.WORKER,
            failure_mode=mode,
            failure_summary=summary,
            spec_version=spec.spec_version,
            spec_hash=spec.spec_hash,
            app_version=__version__,
            datarepo_version=datarepo_version,
            environment=spec.environment,
            credential_profile=spec.credential_profile,
        )
