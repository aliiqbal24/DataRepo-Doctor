from datetime import UTC, datetime

import pytest

from datarepo_doctor.checks import PROBES
from datarepo_doctor.models import Health, ProbeOutcome, ProbeSpec


@pytest.fixture
def probe() -> ProbeSpec:
    return PROBES[0]


def healthy_outcome(spec: ProbeSpec, latency: float = 10) -> ProbeOutcome:
    return ProbeOutcome(
        check_id=spec.check_id,
        health=Health.HEALTHY,
        checked_at=datetime.now(UTC),
        user_query_latency_ms=latency,
        total_probe_duration_ms=latency + 1,
        spec_version=spec.spec_version,
        spec_hash=spec.spec_hash,
        app_version="test",
        datarepo_version="0.0.2",
        environment=spec.environment,
        credential_profile=spec.credential_profile,
    )
