"""Trace summary helpers for list and dashboard views."""

from __future__ import annotations

from typing import Any

from agenttrace.core.grounding import build_grounding_summary
from agenttrace.core.metrics import build_trace_metrics
from agenttrace.core.models import Trace, serialize_datetime


def build_trace_summary(trace: Trace) -> dict[str, Any]:
    metrics = build_trace_metrics(trace)
    grounding = build_grounding_summary(trace)
    approvals = _approval_counts(trace)
    return {
        "trace_id": trace.trace_id,
        "workflow_name": trace.workflow_name,
        "group_id": trace.group_id,
        "status": trace.status,
        "started_at": serialize_datetime(trace.started_at),
        "ended_at": serialize_datetime(trace.ended_at),
        "duration_ms": trace.duration_ms,
        "span_count": metrics["span_count"],
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "estimated_cost": metrics["estimated_cost"],
        "approval_total_count": approvals["total"],
        "approval_pending_count": approvals["pending"],
        "approval_approved_count": approvals["approved"],
        "approval_rejected_count": approvals["rejected"],
        "grounding_status": grounding["status"],
        "unsupported_claim_count": grounding["unsupported_claim_count"],
    }


def build_dashboard_summary(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    total_runs = len(summaries)
    durations = sorted(item["duration_ms"] for item in summaries if item.get("duration_ms") is not None)
    status_counts: dict[str, int] = {}
    workflow_counts: dict[str, int] = {}
    grounding_counts: dict[str, int] = {}

    for item in summaries:
        status = str(item.get("status") or "unknown")
        workflow = str(item.get("workflow_name") or "unknown")
        grounding = str(item.get("grounding_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        workflow_counts[workflow] = workflow_counts.get(workflow, 0) + 1
        grounding_counts[grounding] = grounding_counts.get(grounding, 0) + 1

    return {
        "total_runs": total_runs,
        "status_counts": status_counts,
        "workflow_counts": workflow_counts,
        "grounding_counts": grounding_counts,
        "approval_pending_count": sum(item["approval_pending_count"] for item in summaries),
        "approval_rejected_count": sum(item["approval_rejected_count"] for item in summaries),
        "unsupported_claim_count": sum(item["unsupported_claim_count"] for item in summaries),
        "average_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        "p95_duration_ms": _percentile(durations, 0.95),
        "estimated_cost": round(sum(item["estimated_cost"] for item in summaries), 6),
        "input_tokens": sum(item["input_tokens"] for item in summaries),
        "output_tokens": sum(item["output_tokens"] for item in summaries),
    }


def _approval_counts(trace: Trace) -> dict[str, int]:
    counts = {"total": 0, "pending": 0, "approved": 0, "rejected": 0}
    for span in trace.spans:
        if span.span_type != "approval" and span.span_data.get("approval_required") is not True:
            continue
        counts["total"] += 1
        status = str(span.span_data.get("approval_status") or "unknown")
        if status in {"blocked", "pending"}:
            counts["pending"] += 1
        elif status == "approved":
            counts["approved"] += 1
        elif status == "rejected":
            counts["rejected"] += 1
    return counts


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return values[index]
