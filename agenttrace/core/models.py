"""Trace and span domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

KNOWN_SPAN_TYPES = {
    "agent",
    "generation",
    "function_tool",
    "guardrail",
    "handoff",
    "rag_retrieval",
    "validation",
    "custom",
}


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    return int((ended_at - started_at).total_seconds() * 1000)


@dataclass(frozen=True)
class Span:
    span_id: str
    trace_id: str
    name: str
    span_type: str
    parent_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    input: dict[str, Any] | list[Any] | str | None = None
    output: dict[str, Any] | list[Any] | str | None = None
    error: dict[str, Any] | str | None = None
    span_data: dict[str, Any] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None

    @property
    def duration_ms(self) -> int | None:
        return duration_ms(self.started_at, self.ended_at)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], trace_id: str) -> "Span":
        span_type = str(payload.get("span_type") or payload.get("type") or "custom")
        if span_type not in KNOWN_SPAN_TYPES:
            span_type = "custom"

        usage = payload.get("usage") or {}
        return cls(
            span_id=str(payload["span_id"]),
            trace_id=str(payload.get("trace_id") or trace_id),
            parent_id=payload.get("parent_id") or payload.get("parent_span_id"),
            name=str(payload.get("name") or span_type),
            span_type=span_type,
            started_at=parse_datetime(payload.get("started_at")),
            ended_at=parse_datetime(payload.get("ended_at")),
            input=payload.get("input"),
            output=payload.get("output"),
            error=payload.get("error"),
            span_data=dict(payload.get("span_data") or {}),
            input_tokens=payload.get("input_tokens") or usage.get("input_tokens"),
            output_tokens=payload.get("output_tokens") or usage.get("output_tokens"),
            estimated_cost=payload.get("estimated_cost"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "span_type": self.span_type,
            "started_at": serialize_datetime(self.started_at),
            "ended_at": serialize_datetime(self.ended_at),
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "span_data": self.span_data,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
        }


@dataclass(frozen=True)
class Trace:
    trace_id: str
    workflow_name: str
    status: str
    group_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    spans: list[Span] = field(default_factory=list)

    @property
    def duration_ms(self) -> int | None:
        return duration_ms(self.started_at, self.ended_at)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Trace":
        trace_id = str(payload["trace_id"])
        spans = [Span.from_dict(span, trace_id=trace_id) for span in payload.get("spans", [])]
        return cls(
            trace_id=trace_id,
            workflow_name=str(payload.get("workflow_name") or payload.get("name") or "unknown"),
            group_id=payload.get("group_id"),
            status=str(payload.get("status") or "unknown"),
            metadata=dict(payload.get("metadata") or {}),
            started_at=parse_datetime(payload.get("started_at")),
            ended_at=parse_datetime(payload.get("ended_at")),
            spans=spans,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "workflow_name": self.workflow_name,
            "group_id": self.group_id,
            "status": self.status,
            "metadata": self.metadata,
            "started_at": serialize_datetime(self.started_at),
            "ended_at": serialize_datetime(self.ended_at),
            "duration_ms": self.duration_ms,
            "spans": [span.to_dict() for span in self.spans],
        }

    def format_timeline(self) -> str:
        children_by_parent: dict[str | None, list[Span]] = {}
        for span in self.spans:
            children_by_parent.setdefault(span.parent_id, []).append(span)

        for spans in children_by_parent.values():
            spans.sort(key=lambda span: span.started_at or datetime.min.replace(tzinfo=timezone.utc))

        lines = [
            f"Trace: {self.trace_id}",
            f"Workflow: {self.workflow_name}",
            f"Status: {self.status}",
        ]
        if self.duration_ms is not None:
            lines.append(f"Duration: {self.duration_ms}ms")
        lines.append("")

        def append_span(span: Span, depth: int) -> None:
            indent = "  " * depth
            duration = f" {span.duration_ms}ms" if span.duration_ms is not None else ""
            error = " ERROR" if span.error else ""
            lines.append(f"{indent}- [{span.span_type}] {span.name}{duration}{error}")
            for child in children_by_parent.get(span.span_id, []):
                append_span(child, depth + 1)

        root_spans = children_by_parent.get(None, [])
        for span in root_spans:
            append_span(span, 0)

        return "\n".join(lines)
