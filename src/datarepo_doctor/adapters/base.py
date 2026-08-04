from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from datarepo_doctor.domain.models import PhaseTiming, ProbeSpec


def elapsed_ms(start: int, end: int) -> float:
    return round((end - start) / 1_000_000, 3)


@dataclass(frozen=True)
class AdapterResult:
    rows: list[dict[str, object]]
    user_query_latency_ms: float
    phases: tuple[PhaseTiming, ...]


class ProbeAdapter(Protocol):
    def execute(self, spec: ProbeSpec) -> AdapterResult: ...
