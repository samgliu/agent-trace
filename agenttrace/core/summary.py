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
    memory = _memory_counts(trace)
    source_format = trace.metadata.get("source_format") or _legacy_source_format(trace.metadata)
    source_kind = trace.metadata.get("source_kind") or _legacy_source_kind(trace.metadata)
    ingested_at = trace.metadata.get("ingested_at")
    return {
        "trace_id": trace.trace_id,
        "workflow_name": trace.workflow_name,
        "group_id": trace.group_id,
        "status": execution_status(trace.status),
        "source_format": str(source_format) if source_format else "unknown",
        "source_kind": str(source_kind) if source_kind else "unknown",
        "metadata": trace.metadata,
        "ingested_at": str(ingested_at) if ingested_at else None,
        "started_at": serialize_datetime(trace.started_at),
        "ended_at": serialize_datetime(trace.ended_at),
        "duration_ms": trace.duration_ms,
        "span_count": metrics["span_count"],
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "estimated_cost": metrics["estimated_cost"],
        "error_count": metrics["error_count"],
        "approval_total_count": approvals["total"],
        "approval_pending_count": approvals["pending"],
        "approval_approved_count": approvals["approved"],
        "approval_rejected_count": approvals["rejected"],
        "grounding_status": grounding["status"],
        "unsupported_claim_count": grounding["unsupported_claim_count"],
        "memory_read_count": memory["read_count"],
        "memory_write_count": memory["write_count"],
        "memory_retrieved_count": memory["retrieved_count"],
        "memory_ignored_count": memory["ignored_count"],
        "memory_stale_count": memory["stale_count"],
        "memory_warning_count": memory["warning_count"],
        "memory_average_relevance": memory["average_relevance"],
    }


def build_dashboard_summary(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    total_runs = len(summaries)
    durations = sorted(item["duration_ms"] for item in summaries if item.get("duration_ms") is not None)
    status_counts: dict[str, int] = {}
    workflow_counts: dict[str, int] = {}
    grounding_counts: dict[str, int] = {}
    source_format_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    memory_relevance_scores = [
        item["memory_average_relevance"] for item in summaries if item.get("memory_average_relevance") is not None
    ]

    for item in summaries:
        status = str(item.get("status") or "unknown")
        workflow = str(item.get("workflow_name") or "unknown")
        grounding = str(item.get("grounding_status") or "unknown")
        source_format = str(item.get("source_format") or "unknown")
        source_kind = str(item.get("source_kind") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        workflow_counts[workflow] = workflow_counts.get(workflow, 0) + 1
        grounding_counts[grounding] = grounding_counts.get(grounding, 0) + 1
        source_format_counts[source_format] = source_format_counts.get(source_format, 0) + 1
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1

    return {
        "total_runs": total_runs,
        "status_counts": status_counts,
        "workflow_counts": workflow_counts,
        "grounding_counts": grounding_counts,
        "source_format_counts": source_format_counts,
        "source_kind_counts": source_kind_counts,
        "approval_pending_count": sum(item["approval_pending_count"] for item in summaries),
        "approval_rejected_count": sum(item["approval_rejected_count"] for item in summaries),
        "unsupported_claim_count": sum(item["unsupported_claim_count"] for item in summaries),
        "error_count": sum(item["error_count"] for item in summaries),
        "average_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        "p95_duration_ms": _percentile(durations, 0.95),
        "estimated_cost": round(sum(item["estimated_cost"] for item in summaries), 6),
        "input_tokens": sum(item["input_tokens"] for item in summaries),
        "output_tokens": sum(item["output_tokens"] for item in summaries),
        "memory_read_count": sum(item["memory_read_count"] for item in summaries),
        "memory_write_count": sum(item["memory_write_count"] for item in summaries),
        "memory_retrieved_count": sum(item["memory_retrieved_count"] for item in summaries),
        "memory_ignored_count": sum(item["memory_ignored_count"] for item in summaries),
        "memory_stale_count": sum(item["memory_stale_count"] for item in summaries),
        "memory_warning_count": sum(item["memory_warning_count"] for item in summaries),
        "memory_average_relevance": (
            round(sum(memory_relevance_scores) / len(memory_relevance_scores), 4) if memory_relevance_scores else None
        ),
    }


def execution_status(status: str) -> str:
    if status in {"grounded", "recovered"}:
        return "passed"
    return status


def _legacy_source_format(metadata: dict[str, Any]) -> str:
    source = metadata.get("source")
    if source == "sample" or source == "agenttrace-live-sample":
        return "agenttrace"
    return "unknown"


def _legacy_source_kind(metadata: dict[str, Any]) -> str:
    source = metadata.get("source")
    if source == "agenttrace-live-sample":
        return "live_api"
    if source == "sample":
        return "trace_export"
    return "unknown"


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


def _memory_counts(trace: Trace) -> dict[str, Any]:
    reads = [span for span in trace.spans if span.span_type == "memory_read"]
    writes = [span for span in trace.spans if span.span_type == "memory_write"]
    relevance_scores = [
        span.span_data["memory_relevance_score"]
        for span in reads
        if isinstance(span.span_data.get("memory_relevance_score"), (int, float))
    ]
    ignored_count = sum(1 for span in reads if span.span_data.get("memory_used_in_response") is False)
    stale_count = sum(
        1
        for span in reads
        if isinstance(span.span_data.get("memory_age_seconds"), (int, float))
        and span.span_data["memory_age_seconds"] > 86400 * 90
    )
    low_relevance_count = sum(1 for score in relevance_scores if score < 0.65)
    return {
        "read_count": len(reads),
        "write_count": len(writes),
        "retrieved_count": sum(
            span.span_data["retrieved_memory_count"]
            for span in reads
            if isinstance(span.span_data.get("retrieved_memory_count"), (int, float))
        ),
        "ignored_count": ignored_count,
        "stale_count": stale_count,
        "warning_count": ignored_count + stale_count + low_relevance_count,
        "average_relevance": round(sum(relevance_scores) / len(relevance_scores), 4) if relevance_scores else None,
    }


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return values[index]
