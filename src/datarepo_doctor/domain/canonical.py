"""Canonical result format.

The byte stream is UTF-8 JSON Lines. Line one declares ordered columns and
contract types. Every following line is an ordered array of tagged values.
Objects use sorted compact JSON keys. Decimal values are normalized strings,
floats use an exact hexadecimal representation, and dates/timestamps use ISO
8601 (timestamps are normalized to UTC with a ``Z`` suffix). This format is
internal and versioned as ``drd-canonical-v1``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from .errors import FingerprintMismatch, RowCountMismatch, SchemaMismatch
from .models import ProbeSpec, SchemaField


def _decimal_text(value: Any) -> str:
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal.is_finite():
        raise SchemaMismatch()
    text = format(decimal.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _timestamp_text(value: Any) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise SchemaMismatch()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    parsed: datetime = value
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _date_text(value: Any) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if not isinstance(value, date) or isinstance(value, datetime):
        raise SchemaMismatch()
    parsed: date = value
    return parsed.isoformat()


def canonical_value(value: Any, field: SchemaField) -> dict[str, Any]:
    if value is None:
        if not field.nullable:
            raise SchemaMismatch()
        return {"t": "null"}
    kind = field.type
    if kind == "string" and isinstance(value, str):
        return {"t": "string", "v": value}
    if kind in {"int32", "int64"} and isinstance(value, int) and not isinstance(value, bool):
        return {"t": kind, "v": str(value)}
    if kind == "bool" and isinstance(value, bool):
        return {"t": "bool", "v": value}
    if kind == "decimal":
        return {"t": "decimal", "v": _decimal_text(value)}
    if kind == "float64" and isinstance(value, (float, int)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise SchemaMismatch()
        return {"t": "float64", "v": number.hex()}
    if kind == "date":
        return {"t": "date", "v": _date_text(value)}
    if kind == "timestamp":
        return {"t": "timestamp", "v": _timestamp_text(value)}
    raise SchemaMismatch()


def canonical_bytes(rows: Iterable[Mapping[str, Any]], spec: ProbeSpec) -> bytes:
    materialized = list(rows)
    expected_names = list(spec.selected_columns)
    for row in materialized:
        if list(row.keys()) != expected_names:
            raise SchemaMismatch()
    fields = {field.name: field for field in spec.expected_schema}
    try:
        sorted_rows = sorted(materialized, key=lambda row: tuple(row[key] for key in spec.sort_columns))
    except (KeyError, TypeError) as exc:
        raise SchemaMismatch() from exc
    header = {
        "columns": expected_names,
        "format": "drd-canonical-v1",
        "types": [fields[name].type for name in expected_names],
    }
    lines = [json.dumps(header, sort_keys=True, separators=(",", ":"))]
    for row in sorted_rows:
        values = [canonical_value(row[name], fields[name]) for name in expected_names]
        lines.append(json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(lines) + "\n").encode("utf-8")


def result_sha256(rows: Iterable[Mapping[str, Any]], spec: ProbeSpec) -> str:
    return hashlib.sha256(canonical_bytes(rows, spec)).hexdigest()


def validate_result(rows: list[dict[str, Any]], spec: ProbeSpec) -> str:
    if len(rows) != spec.expected_row_count:
        raise RowCountMismatch(spec.expected_row_count, len(rows))
    actual = result_sha256(rows, spec)
    if actual != spec.expected_sha256:
        raise FingerprintMismatch()
    return actual
