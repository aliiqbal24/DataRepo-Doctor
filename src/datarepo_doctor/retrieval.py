"""The two supported user-facing DataRepo retrieval paths.

This module returns materialized rows only to the isolated child process. Rows
must never be logged, persisted, returned by the API, or sent to the parent.
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any

import httpx

from datarepo_doctor.models import (
    AccessMethod,
    FailureMode,
    ObjectStoreProfile,
    PhaseTiming,
    ProbeSpec,
    Stage,
)
from datarepo_doctor.runner import execution_stage


def _elapsed_ms(start: int, end: int) -> float:
    return round((end - start) / 1_000_000, 3)


@dataclass(frozen=True)
class RetrievalResult:
    rows: list[dict[str, Any]]
    user_query_latency_ms: float
    phases: tuple[PhaseTiming, ...]


def retrieve(spec: ProbeSpec) -> RetrievalResult:
    if spec.access_method == AccessMethod.PYTHON_SDK:
        return _retrieve_with_python(spec)
    return _retrieve_with_roapi(spec)


def query_code(spec: ProbeSpec) -> str:
    """Return a readable, credential-free version of the actual retrieval call."""

    if spec.access_method == AccessMethod.ROAPI_HTTP:
        sql = _build_sql(spec)
        return (
            "import os\n\n"
            "import httpx\n\n"
            f"sql = {sql!r}\n"
            "response = httpx.post(\n"
            "    f\"{os.environ['DOCTOR_ROAPI_URL'].rstrip('/')}/api/sql\",\n"
            "    content=sql.encode(),\n"
            "    headers={\"accept\": \"application/json\", \"content-type\": \"text/plain\"},\n"
            f"    timeout={spec.timeout_seconds!r},\n"
            ")\n"
            "response.raise_for_status()\n"
            "rows = response.json()"
        )

    module_name, catalog_name = spec.catalog.split(":", 1)
    parameters: list[str] = []
    if spec.filters:
        filters = ",\n".join(
            f"        Filter({item.column!r}, {item.operator!r}, {item.value!r})"
            for item in spec.filters
        )
        parameters.append(f"    filters=(\n{filters},\n    )")
    parameters.extend(f"    {name}={value!r}" for name, value in spec.arguments.items())
    parameters.append(f"    columns={list(spec.selected_columns)!r}")
    joined = ",\n".join(parameters)
    return (
        "from datarepo.core import Filter\n"
        f"from {module_name} import {catalog_name}\n\n"
        f"database = {catalog_name}.db({spec.database!r})\n"
        "frame = database.table(\n"
        f"    {spec.table!r},\n"
        f"{joined},\n"
        ").collect()\n"
        "rows = frame.to_dicts()"
    )


def _retrieve_with_python(spec: ProbeSpec) -> RetrievalResult:
    import boto3
    from datarepo.core import Filter

    started = perf_counter_ns()
    with execution_stage(Stage.CATALOG_IMPORT, FailureMode.CATALOG_IMPORT_ERROR):
        module_name, attribute = spec.catalog.split(":", 1)
        catalog = getattr(importlib.import_module(module_name), attribute)
    imported = perf_counter_ns()

    with execution_stage(Stage.TABLE_RESOLUTION, FailureMode.TABLE_NOT_FOUND):
        database = catalog.db(spec.database)
        if spec.table not in database.tables(show_deprecated=True):
            raise KeyError(spec.table)
    resolved = perf_counter_ns()

    kwargs: dict[str, Any] = dict(spec.arguments)
    if spec.filters:
        kwargs["filters"] = tuple(Filter(item.column, item.operator, item.value) for item in spec.filters)
    kwargs["columns"] = list(spec.selected_columns)
    if spec.object_store_profile == ObjectStoreProfile.LOCAL_MINIO:
        os.environ.pop("AWS_SKIP_SIGNATURE", None)
        kwargs["boto3_session"] = boto3.Session(
            aws_access_key_id=os.environ["DOCTOR_S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["DOCTOR_S3_SECRET_KEY"],
            region_name=os.getenv("DOCTOR_S3_REGION", "us-east-1"),
        )
        kwargs["endpoint_url"] = os.environ["DOCTOR_S3_ENDPOINT"]
    elif spec.object_store_profile == ObjectStoreProfile.PUBLIC_AWS_UNSIGNED:
        os.environ["AWS_SKIP_SIGNATURE"] = "true"
        if spec.object_store_region:
            os.environ["AWS_REGION"] = spec.object_store_region

    with execution_stage(Stage.QUERY, FailureMode.QUERY_EXECUTION_ERROR):
        lazy_frame = database.table(spec.table, **kwargs)
        constructed = perf_counter_ns()
        frame = lazy_frame.collect()
        rows = [{column: row[column] for column in spec.selected_columns} for row in frame.to_dicts()]
    materialized = perf_counter_ns()
    return RetrievalResult(
        rows=rows,
        user_query_latency_ms=_elapsed_ms(started, materialized),
        phases=(
            PhaseTiming(name="catalog_import", duration_ms=_elapsed_ms(started, imported)),
            PhaseTiming(name="table_resolution", duration_ms=_elapsed_ms(imported, resolved)),
            PhaseTiming(
                name="query_construction_and_eager_access",
                duration_ms=_elapsed_ms(resolved, constructed),
            ),
            PhaseTiming(
                name="remaining_materialization",
                duration_ms=_elapsed_ms(constructed, materialized),
            ),
        ),
    )


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
                normalized[column] = None
            else:
                raise ValueError("Required response column is absent")
        rows.append(normalized)
    return rows


def _retrieve_with_roapi(spec: ProbeSpec) -> RetrievalResult:
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
    return RetrievalResult(
        rows=rows,
        user_query_latency_ms=_elapsed_ms(started, materialized),
        phases=(
            PhaseTiming(name="request_setup", duration_ms=_elapsed_ms(started, setup)),
            PhaseTiming(name="connect_server_transfer", duration_ms=_elapsed_ms(setup, transferred)),
            PhaseTiming(name="response_decode", duration_ms=_elapsed_ms(transferred, materialized)),
        ),
    )
