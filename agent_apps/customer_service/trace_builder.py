"""Trace and span construction helpers for the customer-service runner."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata


def trace(
    *,
    trace_id: str,
    status: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    spans: list[Span],
    llm_provider: str,
    agent_decision_mode: str,
    supervisor_route: str,
    conversation_history_count: int = 0,
) -> Trace:
    result = Trace(
        trace_id=trace_id,
        workflow_name="support-triage",
        status=status,
        metadata={
            "source": "agenttrace-agent-runner",
            "runner": "agent_apps.customer_service.runner",
            "llm_provider": llm_provider,
            "agent_decision_mode": agent_decision_mode,
            "supervisor_route": supervisor_route,
            "conversation_history_count": conversation_history_count,
        },
        raw_payload=None,
        started_at=started_at,
        ended_at=ended_at,
        spans=spans,
    )
    return with_source_metadata(result, source_format="agenttrace", source_kind="agent_runner")


def span(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    span_type: str,
    clock: "SpanClock",
    duration_ms: int,
    parent_id: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    span_data: dict[str, Any] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost: float | None = None,
) -> Span:
    started_at, ended_at = clock.next(duration_ms)
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        parent_id=parent_id,
        name=name,
        span_type=span_type,
        started_at=started_at,
        ended_at=ended_at,
        input=input,
        output=output,
        error=error,
        span_data=span_data or {},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )


def span_id(trace_id: str, suffix: str) -> str:
    return f"{trace_id}_{suffix}"


class SpanClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def next(self, duration_ms: int) -> tuple[datetime, datetime]:
        started_at = self.current
        ended_at = started_at + timedelta(milliseconds=duration_ms)
        self.current = ended_at
        return started_at, ended_at
