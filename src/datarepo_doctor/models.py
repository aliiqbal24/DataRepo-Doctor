from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccessMethod(StrEnum):
    PYTHON_SDK = "python_sdk"
    ROAPI_HTTP = "roapi_http"


class ObjectStoreProfile(StrEnum):
    NONE = "none"
    LOCAL_MINIO = "local_minio"
    PUBLIC_AWS_UNSIGNED = "public_aws_unsigned"


class Health(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class FailureMode(StrEnum):
    CONNECTION_ERROR = "connection_error"
    QUERY_ERROR = "query_error"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT = "timeout"
    WORKER_CRASH = "worker_crash"


class FilterClause(BaseModel):
    model_config = ConfigDict(frozen=True)
    column: str
    operator: Literal["=", "!=", "<", "<=", ">", ">=", "in", "not in"]
    value: Any


class SchemaField(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    type: Literal["string", "int32", "int64", "float64", "decimal", "bool", "date", "timestamp"]
    nullable: bool = False


_SECRET_PATTERN = re.compile(
    r"(password|secret|token|access[_-]?key|credential|postgres(?:ql)?://[^/\s:@]+:[^@\s]+@)",
    re.IGNORECASE,
)


class ProbeSpec(BaseModel):
    """A complete, bounded, secret-free retrieval and validation contract."""

    model_config = ConfigDict(frozen=True)

    check_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    display_name: str
    description: str
    physical_source: str
    source_owner: str = "Local fixture"
    source_uri: str = "local://fixture"
    source_version: str = "fixture-v1"
    source_license: str = "Project test fixture"
    source_documentation_url: str | None = None
    catalog: str
    database: str
    table: str
    access_method: AccessMethod
    filters: tuple[FilterClause, ...] = ()
    arguments: dict[str, Any] = Field(default_factory=dict)
    selected_columns: tuple[str, ...]
    sort_columns: tuple[str, ...]
    expected_schema: tuple[SchemaField, ...]
    expected_row_count: int = Field(ge=0)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    timeout_seconds: float = Field(gt=0, le=300)
    default_interval_minutes: int = Field(default=60, ge=5, le=10080)
    phase_offset_minutes: int = Field(ge=0)
    environment: str = "local"
    credential_profile: Literal["doctor_reader"] = "doctor_reader"
    object_store_profile: ObjectStoreProfile = ObjectStoreProfile.NONE
    object_store_region: str | None = None
    query_description: str
    display_result_rows: bool = False
    spec_version: str = "1"

    @model_validator(mode="after")
    def validate_safety(self) -> ProbeSpec:
        if not self.filters and not self.arguments:
            raise ValueError("probe must be explicitly bounded by filters or function arguments")
        if not self.selected_columns:
            raise ValueError("selected_columns must not be empty")
        if len(set(self.selected_columns)) != len(self.selected_columns):
            raise ValueError("selected_columns must be unique")
        schema_columns = tuple(field.name for field in self.expected_schema)
        if schema_columns != self.selected_columns:
            raise ValueError("expected schema must exactly match selected column order")
        if not self.sort_columns or not set(self.sort_columns).issubset(self.selected_columns):
            raise ValueError("sort_columns must be a non-empty subset of selected_columns")
        safe_payload = json.dumps(
            {
                "description": self.description,
                "arguments": self.arguments,
                "query_description": self.query_description,
            },
            default=str,
        )
        if _SECRET_PATTERN.search(safe_payload):
            raise ValueError("probe specifications may not contain secrets or credential URLs")
        return self

    @property
    def spec_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"expected_sha256"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ProbeOutcome(BaseModel):
    """The only probe data allowed to cross the child-process boundary."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    health: Health
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    user_query_latency_ms: float | None = None
    result_rows: tuple[dict[str, Any], ...] = ()
    failure_mode: FailureMode | None = None
    failure_summary: str | None = None
    failure_detail: str | None = Field(default=None, max_length=300)
    spec_version: str
    spec_hash: str
    app_version: str
    datarepo_version: str
    environment: str
    credential_profile: str

    @model_validator(mode="after")
    def enforce_binary_contract(self) -> ProbeOutcome:
        failure_values = (self.failure_mode, self.failure_summary, self.failure_detail)
        if self.health == Health.HEALTHY:
            if self.user_query_latency_ms is None:
                raise ValueError("healthy outcomes require query latency")
            if any(failure_values):
                raise ValueError("healthy outcomes cannot contain failure details")
        else:
            if self.user_query_latency_ms is not None:
                raise ValueError("unhealthy outcomes must not expose query latency")
            if self.result_rows:
                raise ValueError("unhealthy outcomes cannot contain result rows")
            if self.failure_mode is None:
                raise ValueError("unhealthy outcomes require a failure mode")
        return self
