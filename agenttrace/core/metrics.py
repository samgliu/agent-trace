"""Metrics helpers for trace analysis."""

from __future__ import annotations

from typing import Any

from agenttrace.core.models import Span, Trace


def build_trace_metrics(trace: Trace) -> dict[str, Any]:
    spans = trace.spans
    input_tokens = sum(span.input_tokens or 0 for span in spans)
    output_tokens = sum(span.output_tokens or 0 for span in spans)
    estimated_cost = sum(span.estimated_cost or 0 for span in spans)
    spans_by_type: dict[str, int] = {}
    for span in spans:
        spans_by_type[span.span_type] = spans_by_type.get(span.span_type, 0) + 1

    slowest_span = max(spans, key=lambda span: span.duration_ms or -1, default=None)
    most_expensive_span = max(spans, key=lambda span: span.estimated_cost or -1, default=None)

    return {
        "trace_id": trace.trace_id,
        "workflow_name": trace.workflow_name,
        "status": trace.status,
        "duration_ms": trace.duration_ms,
        "span_count": len(spans),
        "spans_by_type": spans_by_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost": round(estimated_cost, 6),
        "slowest_span": _span_summary(slowest_span),
        "most_expensive_span": _span_summary(most_expensive_span),
    }


def _span_summary(span: Span | None) -> dict[str, Any] | None:
    if span is None:
        return None
    return {
        "span_id": span.span_id,
        "name": span.name,
        "span_type": span.span_type,
        "duration_ms": span.duration_ms,
        "estimated_cost": span.estimated_cost,
    }
