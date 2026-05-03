"""API request schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


class SpanIngestRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    span_id: str
    parent_id: str | None = None
    parent_span_id: str | None = None
    name: str | None = None
    span_type: str | None = None
    type: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    input: JsonValue = None
    output: JsonValue = None
    error: JsonValue = None
    span_data: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    usage: dict[str, Any] | None = None


class TraceIngestRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    trace_id: str
    workflow_name: str | None = None
    name: str | None = None
    group_id: str | None = None
    status: str = "running"
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    ended_at: str | None = None
    spans: list[SpanIngestRequest] = Field(default_factory=list)


class TraceLifecycleUpdateRequest(BaseModel):
    status: Literal["running", "passed", "failed", "cancelled", "recovered", "grounded"] | None = None
    ended_at: str | None = None

