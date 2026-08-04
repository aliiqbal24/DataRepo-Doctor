from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from datarepo_doctor.domain.models import FailureMode, Stage


@dataclass
class StageError(Exception):
    stage: Stage
    default_mode: FailureMode
    cause: BaseException


@contextmanager
def execution_stage(stage: Stage, default_mode: FailureMode) -> Iterator[None]:
    try:
        yield
    except StageError:
        raise
    except BaseException as exc:
        raise StageError(stage, default_mode, exc) from exc
