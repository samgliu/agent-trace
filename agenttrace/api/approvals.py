"""Approval span mutation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from agenttrace.api.event_bus import EventBus
from agenttrace.core.models import Span, Trace
from agenttrace.storage.sqlite import SQLiteTraceStore


def update_approval_span(
    store: SQLiteTraceStore,
    trace_id: str,
    span_id: str,
    status: str,
    *,
    event_bus: EventBus | None = None,
) -> Span:
    trace = _require_trace(store, trace_id)
    span = store.get_span(trace_id, span_id)
    if span is None:
        raise HTTPException(status_code=404, detail=f"Span not found: {span_id}")
    if span.span_type != "approval" and span.span_data.get("approval_required") is not True:
        raise HTTPException(status_code=400, detail=f"Span is not an approval gate: {span_id}")

    span_data = dict(span.span_data)
    output = dict(span.output) if isinstance(span.output, dict) else {}
    span_data["approval_status"] = status
    output["approval_status"] = status

    if status == "blocked":
        span_data["approved_by"] = None
        span_data["approved_at"] = None
        output["approved_by"] = None
        output["approved_at"] = None
    else:
        approved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        span_data["approved_by"] = "demo_user"
        span_data["approved_at"] = approved_at
        output["approved_by"] = "demo_user"
        output["approved_at"] = approved_at

    updated = store.update_span_payload(trace_id, span_id, output=output, span_data=span_data)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Span not found: {span_id}")
    _append_approval_chat_message(store, trace, updated, status)
    if event_bus is not None:
        _publish_trace_events(event_bus, "approval.updated", trace_id, span_id=span_id)
        session_id = trace.metadata.get("chat_session_id")
        if isinstance(session_id, str):
            event_bus.publish(
                "chat.message.created",
                resource_type="chat_session",
                resource_id=session_id,
                session_id=session_id,
                trace_id=trace_id,
            )
    return updated


def _append_approval_chat_message(store: SQLiteTraceStore, trace: Trace, span: Span, status: str) -> None:
    session_id = trace.metadata.get("chat_session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    status_label = {"approved": "approved", "rejected": "rejected", "blocked": "reverted"}.get(status, status)
    content = _approval_chat_content(status)
    store.add_chat_message(
        session_id,
        role="assistant",
        content=content,
        trace_id=trace.trace_id,
        metadata={
            "event_type": "approval_decision",
            "approval_status": status_label,
            "approval_span_id": span.span_id,
        },
    )


def _approval_chat_content(status: str) -> str:
    if status == "approved":
        return "Human approval was granted for this support action. I can proceed with the approved next step."
    if status == "rejected":
        return (
            "Human approval was rejected for this support action. I cannot proceed with that action, "
            "but I can review any additional evidence or offer the next policy-safe option."
        )
    return "The approval decision was reverted. The support action is waiting for human review again."


def _require_trace(store: SQLiteTraceStore, trace_id: str) -> Trace:
    trace = store.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
    return trace


def _publish_trace_events(event_bus: EventBus, event_type: str, trace_id: str, **extra: Any) -> None:
    event_bus.publish(event_type, resource_type="trace", resource_id=trace_id, trace_id=trace_id, **extra)
    event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")
