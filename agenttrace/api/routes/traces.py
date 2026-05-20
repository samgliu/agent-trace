"""Trace route registration."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query

from agenttrace.adapters.openai_agents import normalize_openai_agents_trace
from agenttrace.api.event_bus import EventBus
from agenttrace.api.schemas import SpanIngestRequest, TraceIngestRequest, TraceLifecycleUpdateRequest
from agenttrace.core.grounding import build_grounding_summary
from agenttrace.core.importer import normalize_trace
from agenttrace.core.metrics import build_trace_metrics
from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agenttrace.storage.sqlite import SQLiteTraceStore

RequireTrace = Callable[[SQLiteTraceStore, str], Trace]
PublishTraceEvents = Callable[..., None]
UpdateApprovalSpan = Callable[..., Span]


def register_trace_routes(
    app: FastAPI,
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    require_trace: RequireTrace,
    publish_trace_events: PublishTraceEvents,
    update_approval_span: UpdateApprovalSpan,
) -> None:
    @app.get("/traces")
    def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        workflow_name: str | None = None,
        approval_status: str | None = Query(None, pattern="^(pending|approved|rejected|none)$"),
        grounding_status: str | None = None,
        source_format: str | None = None,
        source_kind: str | None = None,
        chat_session_id: str | None = None,
        has_errors: bool | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> dict[str, Any]:
        return trace_store.list_trace_summaries(
            limit=limit,
            offset=offset,
            status=status,
            workflow_name=workflow_name,
            approval_status=approval_status,
            grounding_status=grounding_status,
            source_format=source_format,
            source_kind=source_kind,
            chat_session_id=chat_session_id,
            has_errors=has_errors,
            started_after=started_after,
            started_before=started_before,
        )

    @app.get("/trace-summaries")
    def trace_summaries(trace_ids: str = Query("")) -> list[dict[str, Any]]:
        ids = [trace_id.strip() for trace_id in trace_ids.split(",") if trace_id.strip()]
        return trace_store.trace_summaries_by_ids(ids)

    @app.post("/traces")
    def ingest_trace(payload: TraceIngestRequest) -> dict[str, Any]:
        trace = with_source_metadata(
            normalize_trace(payload.model_dump()),
            source_format="agenttrace",
            source_kind="live_api",
        )
        trace_store.upsert_trace(trace)
        publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/ingest/openai-agents")
    def ingest_openai_agents_trace(payload: dict[str, Any]) -> dict[str, Any]:
        trace = normalize_openai_agents_trace(payload)
        trace_store.upsert_trace(trace)
        for span in trace.spans:
            trace_store.upsert_span(span)
        publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/traces/{trace_id}/spans")
    def ingest_span(trace_id: str, payload: SpanIngestRequest) -> dict[str, Any]:
        require_trace(trace_store, trace_id)
        span = Span.from_dict({**payload.model_dump(), "trace_id": trace_id}, trace_id=trace_id)
        saved = trace_store.upsert_span(span)
        publish_trace_events(event_bus, "span.updated", trace_id, span_id=saved.span_id)
        return saved.to_dict()

    @app.patch("/traces/{trace_id}")
    def update_trace(trace_id: str, payload: TraceLifecycleUpdateRequest) -> dict[str, Any]:
        updated = trace_store.update_trace_lifecycle(
            trace_id,
            status=payload.status,
            ended_at=payload.ended_at,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
        publish_trace_events(event_bus, "trace.updated", trace_id)
        return updated.to_dict()

    @app.get("/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        trace = require_trace(trace_store, trace_id)
        return trace.to_dict()

    @app.get("/traces/{trace_id}/raw")
    def get_raw_trace(trace_id: str) -> dict[str, Any] | list[Any]:
        trace = require_trace(trace_store, trace_id)
        return trace.raw_payload or trace.to_dict()

    @app.get("/traces/{trace_id}/spans")
    def get_spans(trace_id: str) -> list[dict[str, Any]]:
        trace = require_trace(trace_store, trace_id)
        return [span.to_dict() for span in trace.spans]

    @app.get("/traces/{trace_id}/metrics")
    def get_metrics(trace_id: str) -> dict[str, Any]:
        trace = require_trace(trace_store, trace_id)
        return build_trace_metrics(trace)

    @app.get("/traces/{trace_id}/grounding")
    def get_grounding(trace_id: str) -> dict[str, Any]:
        trace = require_trace(trace_store, trace_id)
        return build_grounding_summary(trace)

    @app.post("/traces/{trace_id}/approvals/{span_id}/approve")
    def approve_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return update_approval_span(trace_store, trace_id, span_id, "approved", event_bus=event_bus).to_dict()

    @app.post("/traces/{trace_id}/approvals/{span_id}/reject")
    def reject_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return update_approval_span(trace_store, trace_id, span_id, "rejected", event_bus=event_bus).to_dict()

    @app.post("/traces/{trace_id}/approvals/{span_id}/revert")
    def revert_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return update_approval_span(trace_store, trace_id, span_id, "blocked", event_bus=event_bus).to_dict()
