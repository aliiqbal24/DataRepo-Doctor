from __future__ import annotations

import json
import os
from time import perf_counter_ns
from typing import Any

import httpx

from datarepo_doctor.domain.models import FailureMode, PhaseTiming, ProbeSpec, Stage
from datarepo_doctor.execution.context import execution_stage

from .base import AdapterResult, elapsed_ms


def _sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, list):
        return "(" + ",".join(_sql_literal(item) for item in value) + ")"
    raise ValueError("Unsupported bounded filter literal")


def _build_sql(spec: ProbeSpec) -> str:
    operators = {"in": "IN", "not in": "NOT IN"}
    predicates = [
        f'"{item.column}" {operators.get(item.operator, item.operator)} {_sql_literal(item.value)}'
        for item in spec.filters
    ]
    columns = ", ".join(f'"{column}"' for column in spec.selected_columns)
    order = ", ".join(f'"{column}"' for column in spec.sort_columns)
    return (
        f'SELECT {columns} FROM "{spec.database}_{spec.table}" WHERE '
        + " AND ".join(predicates)
        + f" ORDER BY {order}"
    )


def _normalize_json_rows(decoded: object, spec: ProbeSpec) -> list[dict[str, Any]]:
    if not isinstance(decoded, list) or not all(isinstance(row, dict) for row in decoded):
        raise ValueError("Unexpected response shape")
    nullable = {field.name for field in spec.expected_schema if field.nullable}
    rows: list[dict[str, Any]] = []
    for row in decoded:
        normalized: dict[str, Any] = {}
        for column in spec.selected_columns:
            if column in row:
                normalized[column] = row[column]
            elif column in nullable:
                # ROAPI omits null-valued properties from its JSON object encoding.
                normalized[column] = None
            else:
                raise ValueError("Required response column is absent")
        rows.append(normalized)
    return rows


class RoapiHttpAdapter:
    def execute(self, spec: ProbeSpec) -> AdapterResult:
        started = perf_counter_ns()
        sql = _build_sql(spec)
        setup = perf_counter_ns()
        with execution_stage(Stage.QUERY, FailureMode.HTTP_ERROR):
            response = httpx.post(
                f"{os.environ['DOCTOR_ROAPI_URL'].rstrip('/')}/api/sql",
                content=sql.encode(),
                headers={"accept": "application/json", "content-type": "text/plain"},
                timeout=spec.timeout_seconds,
            )
            response.raise_for_status()
        transferred = perf_counter_ns()
        with execution_stage(Stage.RESPONSE_DECODE, FailureMode.RESPONSE_DECODE_ERROR):
            decoded = json.loads(response.content)
            rows = _normalize_json_rows(decoded, spec)
        materialized = perf_counter_ns()
        return AdapterResult(
            rows=rows,
            user_query_latency_ms=elapsed_ms(started, materialized),
            phases=(
                PhaseTiming(name="request_setup", duration_ms=elapsed_ms(started, setup)),
                PhaseTiming(name="connect_server_transfer", duration_ms=elapsed_ms(setup, transferred)),
                PhaseTiming(name="response_decode", duration_ms=elapsed_ms(transferred, materialized)),
            ),
        )
