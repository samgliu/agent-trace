"""OpenAI Agents trace adapter.

The official Agents docs describe traces as structured records of workflow runs,
model calls, tool calls, handoffs, guardrails, and custom spans. This adapter
keeps provider-specific field names at the boundary and normalizes them into
AgentTrace's internal Trace/Span model.
"""

from __future__ import annotations

from typing import Any

from agenttrace.core.models import Span, Trace, parse_datetime


SPAN_TYPE_MAP = {
    "agent": "agent",
    "agent_span": "agent",
    "generation": "generation",
    "generation_span": "generation",
    "model_call": "generation",
    "response": "generation",
    "tool": "function_tool",
    "tool_call": "function_tool",
    "function_tool": "function_tool",
    "handoff": "handoff",
    "handoff_span": "handoff",
    "guardrail": "guardrail",
    "guardrail_span": "guardrail",
    "custom": "custom",
    "custom_span": "custom",
}


def normalize_openai_agents_trace(payload: dict[str, Any]) -> Trace:
    if "events" in payload:
        return _normalize_event_stream(payload)
    return _normalize_trace_export(payload)


def _normalize_trace_export(payload: dict[str, Any]) -> Trace:
    trace_id = _string_value(payload, "trace_id", "id", default="unknown")
    spans = [_normalize_span(span, trace_id=trace_id) for span in payload.get("spans", [])]
    return Trace(
        trace_id=trace_id,
        workflow_name=_string_value(payload, "workflow_name", "name", "trace_name", default="unknown"),
        group_id=payload.get("group_id"),
        status=_string_value(payload, "status", default="unknown"),
        metadata=dict(payload.get("metadata") or {}),
        raw_payload=payload,
        started_at=parse_datetime(payload.get("started_at")),
        ended_at=parse_datetime(payload.get("ended_at")),
        spans=spans,
    )


def _normalize_event_stream(payload: dict[str, Any]) -> Trace:
    events = payload.get("events") or []
    trace_id = _string_value(payload, "trace_id", "id", default="unknown")
    workflow_name = _string_value(payload, "workflow_name", "name", default="unknown")
    status = _string_value(payload, "status", default="running")
    metadata = dict(payload.get("metadata") or {})
    started_at = payload.get("started_at")
    ended_at = payload.get("ended_at")
    spans_by_id: dict[str, dict[str, Any]] = {}

    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event") or event.get("type") or "")
        data = event.get("data") if isinstance(event.get("data"), dict) else event
        if event_type in {"trace_started", "trace.start", "trace_started_event"}:
            trace_id = _string_value(data, "trace_id", "id", default=trace_id)
            workflow_name = _string_value(data, "workflow_name", "name", default=workflow_name)
            status = _string_value(data, "status", default=status)
            started_at = data.get("started_at") or data.get("timestamp") or started_at
            metadata.update(dict(data.get("metadata") or {}))
        elif event_type in {"trace_completed", "trace.ended", "trace_finished"}:
            status = _string_value(data, "status", default="passed")
            ended_at = data.get("ended_at") or data.get("timestamp") or ended_at
        elif event_type in {"span_started", "span.start"}:
            span_id = _string_value(data, "span_id", "id", default="")
            if span_id:
                spans_by_id[span_id] = {**spans_by_id.get(span_id, {}), **data}
                spans_by_id[span_id]["started_at"] = data.get("started_at") or data.get("timestamp")
        elif event_type in {"span_completed", "span.ended", "span_finished"}:
            span_id = _string_value(data, "span_id", "id", default="")
            if span_id:
                spans_by_id[span_id] = {**spans_by_id.get(span_id, {}), **data}
                spans_by_id[span_id]["ended_at"] = data.get("ended_at") or data.get("timestamp")

    trace_payload = {
        "trace_id": trace_id,
        "workflow_name": workflow_name,
        "status": status,
        "metadata": metadata,
        "started_at": started_at,
        "ended_at": ended_at,
        "spans": [],
    }
    trace = Trace.from_dict(trace_payload)
    return Trace(
        trace_id=trace.trace_id,
        workflow_name=trace.workflow_name,
        group_id=trace.group_id,
        status=trace.status,
        metadata=trace.metadata,
        raw_payload=payload,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        spans=[_normalize_span(span, trace_id=trace.trace_id) for span in spans_by_id.values()],
    )


def _normalize_span(payload: dict[str, Any], *, trace_id: str) -> Span:
    span_type = _mapped_span_type(payload)
    span_data = dict(payload.get("span_data") or payload.get("data") or {})
    if "agent_name" in payload:
        span_data["agent_name"] = payload["agent_name"]
    if "tool_name" in payload:
        span_data["tool_name"] = payload["tool_name"]
    if "model" in payload:
        span_data["model"] = payload["model"]
    if span_type == "handoff":
        for key in ("from_agent", "to_agent"):
            if key in payload:
                span_data[key] = payload[key]
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    normalized = {
        "span_id": _string_value(payload, "span_id", "id", default="unknown"),
        "trace_id": trace_id,
        "parent_id": payload.get("parent_id") or payload.get("parent_span_id"),
        "name": _span_name(payload, span_type),
        "span_type": span_type,
        "started_at": payload.get("started_at") or payload.get("start_time"),
        "ended_at": payload.get("ended_at") or payload.get("end_time"),
        "input": payload.get("input"),
        "output": payload.get("output"),
        "error": payload.get("error"),
        "span_data": span_data,
        "input_tokens": _first_number(payload, usage, "input_tokens", "prompt_tokens"),
        "output_tokens": _first_number(payload, usage, "output_tokens", "completion_tokens"),
        "estimated_cost": _first_number(payload, usage, "estimated_cost", "cost", "total_cost"),
    }
    return Span.from_dict(normalized, trace_id=trace_id)


def _mapped_span_type(payload: dict[str, Any]) -> str:
    raw_type = str(payload.get("span_type") or payload.get("type") or payload.get("kind") or "custom")
    return SPAN_TYPE_MAP.get(raw_type, "custom")


def _span_name(payload: dict[str, Any], span_type: str) -> str:
    if payload.get("name"):
        return str(payload["name"])
    if span_type == "generation":
        return str(payload.get("model") or "Model call")
    if span_type == "function_tool":
        return str(payload.get("tool_name") or "Tool call")
    if span_type == "handoff":
        from_agent = payload.get("from_agent")
        to_agent = payload.get("to_agent")
        if from_agent and to_agent:
            return f"{from_agent} -> {to_agent}"
    return span_type


def _string_value(payload: dict[str, Any], *keys: str, default: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value)
    return default


def _first_number(*items: Any) -> int | float | None:
    payloads = [item for item in items if isinstance(item, dict)]
    keys = [item for item in items if isinstance(item, str)]
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return value
    return None
