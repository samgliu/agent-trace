"""AgentTrace API application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agenttrace.core.metrics import build_trace_metrics
from agenttrace.core.models import Trace
from agenttrace.storage.sqlite import SQLiteTraceStore

DEFAULT_DB_PATH = Path(".agenttrace") / "agenttrace.db"


def create_app(store: SQLiteTraceStore | None = None) -> FastAPI:
    app = FastAPI(
        title="AgentTrace API",
        version="0.1.0",
        description="Trace analysis API for multi-agent AI workflows.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    trace_store = store or SQLiteTraceStore(_database_path())
    trace_store.initialize()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/traces")
    def list_traces() -> list[dict[str, Any]]:
        return [trace.to_dict() for trace in trace_store.list_traces()]

    @app.get("/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        trace = _require_trace(trace_store, trace_id)
        return trace.to_dict()

    @app.get("/traces/{trace_id}/spans")
    def get_spans(trace_id: str) -> list[dict[str, Any]]:
        trace = _require_trace(trace_store, trace_id)
        return [span.to_dict() for span in trace.spans]

    @app.get("/traces/{trace_id}/metrics")
    def get_metrics(trace_id: str) -> dict[str, Any]:
        trace = _require_trace(trace_store, trace_id)
        return build_trace_metrics(trace)

    @app.post("/traces/{trace_id}/approvals/{span_id}/approve")
    def approve_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return _update_approval_span(trace_store, trace_id, span_id, "approved").to_dict()

    @app.post("/traces/{trace_id}/approvals/{span_id}/reject")
    def reject_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return _update_approval_span(trace_store, trace_id, span_id, "rejected").to_dict()

    @app.post("/traces/{trace_id}/approvals/{span_id}/revert")
    def revert_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return _update_approval_span(trace_store, trace_id, span_id, "blocked").to_dict()

    return app


def _database_path() -> Path:
    return Path(os.environ.get("AGENTTRACE_DB", str(DEFAULT_DB_PATH)))


def _require_trace(store: SQLiteTraceStore, trace_id: str) -> Trace:
    trace = store.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
    return trace


def _update_approval_span(
    store: SQLiteTraceStore,
    trace_id: str,
    span_id: str,
    status: str,
):
    _require_trace(store, trace_id)
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
    return updated


app = create_app()
