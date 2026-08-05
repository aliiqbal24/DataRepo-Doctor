from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from datarepo_doctor.models import AccessMethod, ProbeSpec, SchemaField
from datarepo_doctor.validation import (
    FingerprintMismatch,
    RowCountMismatch,
    SchemaMismatch,
    canonical_bytes,
    result_sha256,
    validate_result,
)


def all_types_spec(expected_sha256: str = "0" * 64, count: int = 1) -> ProbeSpec:
    fields = (
        SchemaField(name="id", type="int64"),
        SchemaField(name="name", type="string"),
        SchemaField(name="amount", type="decimal"),
        SchemaField(name="ratio", type="float64"),
        SchemaField(name="day", type="date"),
        SchemaField(name="at", type="timestamp"),
        SchemaField(name="active", type="bool"),
        SchemaField(name="maybe", type="string", nullable=True),
    )
    return ProbeSpec(
        check_id="canonical-test",
        display_name="Canonical",
        description="test",
        physical_source="test",
        catalog="x:y",
        database="db",
        table="table",
        access_method=AccessMethod.PYTHON_SDK,
        arguments={"lower": 1, "upper": 1},
        selected_columns=tuple(f.name for f in fields),
        sort_columns=("id",),
        expected_schema=fields,
        expected_row_count=count,
        expected_sha256=expected_sha256,
        timeout_seconds=5,
        phase_offset_minutes=0,
        query_description="bounded test query",
    )


def row():
    return {
        "id": 1,
        "name": "µ",
        "amount": Decimal("10.5000"),
        "ratio": 0.5,
        "day": date(2026, 1, 2),
        "at": datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        "active": True,
        "maybe": None,
    }


def test_canonical_serialization_is_stable_and_explicit():
    payload = canonical_bytes([row()], all_types_spec())
    assert payload == canonical_bytes([row()], all_types_spec())
    assert b"drd-canonical-v1" in payload
    assert b"0x1.0000000000000p-1" in payload
    assert b"10.5" in payload
    assert b"null" in payload


def test_validation_failure_modes():
    spec = all_types_spec(count=2)
    with pytest.raises(RowCountMismatch):
        validate_result([row()], spec)
    actual = result_sha256([row()], all_types_spec())
    with pytest.raises(FingerprintMismatch):
        validate_result([row()], all_types_spec("f" * 64))
    validate_result([row()], all_types_spec(actual))
    bad = dict(row())
    bad["id"] = "1"
    with pytest.raises(SchemaMismatch):
        result_sha256([bad], all_types_spec())


def test_column_order_is_part_of_schema():
    reversed_row = dict(reversed(list(row().items())))
    with pytest.raises(SchemaMismatch):
        canonical_bytes([reversed_row], all_types_spec())
