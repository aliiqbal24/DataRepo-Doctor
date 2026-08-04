from __future__ import annotations

from .models import FailureMode


class ProbeError(Exception):
    mode: FailureMode

    def __init__(self, mode: FailureMode, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.mode = mode
        self.safe_summary = safe_summary


class SchemaMismatch(ProbeError):
    def __init__(self) -> None:
        super().__init__(FailureMode.SCHEMA_MISMATCH, "Result schema did not match the contract.")


class RowCountMismatch(ProbeError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            FailureMode.ROW_COUNT_MISMATCH,
            f"Expected {expected} rows but materialized {actual} rows.",
        )


class FingerprintMismatch(ProbeError):
    def __init__(self) -> None:
        super().__init__(
            FailureMode.RESULT_FINGERPRINT_MISMATCH,
            "Result fingerprint did not match the bounded fixture contract.",
        )
