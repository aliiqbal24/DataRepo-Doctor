from __future__ import annotations

import importlib
import os
from time import perf_counter_ns
from typing import Any

import boto3
from datarepo.core import Filter

from datarepo_doctor.domain.models import (
    FailureMode,
    ObjectStoreProfile,
    PhaseTiming,
    ProbeSpec,
    Stage,
)
from datarepo_doctor.execution.context import execution_stage

from .base import AdapterResult, elapsed_ms


class PythonDataRepoAdapter:
    def execute(self, spec: ProbeSpec) -> AdapterResult:
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
            # DataRepo delegates public S3 reads to delta-rs/Polars. Both honor
            # these object-store settings when no signed boto3 session is passed.
            os.environ["AWS_SKIP_SIGNATURE"] = "true"
            if spec.object_store_region:
                os.environ["AWS_REGION"] = spec.object_store_region

        with execution_stage(Stage.QUERY, FailureMode.QUERY_EXECUTION_ERROR):
            lazy_frame = database.table(spec.table, **kwargs)
            constructed = perf_counter_ns()
            frame = lazy_frame.collect()
            rows = [{column: row[column] for column in spec.selected_columns} for row in frame.to_dicts()]
        materialized = perf_counter_ns()
        return AdapterResult(
            rows=rows,
            user_query_latency_ms=elapsed_ms(started, materialized),
            phases=(
                PhaseTiming(name="catalog_import", duration_ms=elapsed_ms(started, imported)),
                PhaseTiming(name="table_resolution", duration_ms=elapsed_ms(imported, resolved)),
                PhaseTiming(
                    name="query_construction_and_eager_access",
                    duration_ms=elapsed_ms(resolved, constructed),
                ),
                PhaseTiming(
                    name="remaining_materialization",
                    duration_ms=elapsed_ms(constructed, materialized),
                ),
            ),
        )
