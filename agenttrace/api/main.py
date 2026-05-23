"""AgentTrace API application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agenttrace.api.event_bus import EventBus
from agenttrace.api.agent_service import run_support_triage_agent
from agenttrace.api.approvals import update_approval_span
from agenttrace.api.auth import auth_config_from_env, register_auth
from agenttrace.api.chat_sessions import (
    assistant_response_from_trace,
    conversation_history,
    start_async_chat_turn,
    with_chat_metadata,
)
from agenttrace.api.eval_runs import (
    build_eval_comparison,
    eval_case_result_has_provider_issue,
    eval_run_is_degraded,
    execute_eval_cases,
    llm_runtime_error_status,
    save_eval_progress,
    with_eval_metadata,
)
from agenttrace.api.routes.chat import register_chat_routes
from agenttrace.api.routes.evals import register_eval_routes
from agenttrace.api.routes.traces import register_trace_routes
from agenttrace.api.routes.workflows import (
    WorkflowRunRegistry,
    reconcile_stale_workflow_runs,
    register_workflow_routes,
)
from agenttrace.core.models import Trace
from agenttrace.core.summary import build_dashboard_summary
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
            "http://web:5173",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )
    register_auth(app, auth_config_from_env())
    trace_store = store or SQLiteTraceStore(_database_path())
    trace_store.initialize()
    event_bus = EventBus()
    workflow_runs = WorkflowRunRegistry(trace_store)
    reconcile_stale_workflow_runs(trace_store, workflow_runs)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/events")
    def events() -> StreamingResponse:
        return StreamingResponse(event_bus.stream(), media_type="text/event-stream")

    @app.get("/dashboard/summary")
    def dashboard_summary() -> dict[str, Any]:
        return build_dashboard_summary(trace_store.all_trace_summaries())

    @app.get("/workflows")
    def list_workflows() -> list[str]:
        return sorted(trace_store.workflow_names())

    register_eval_routes(
        app,
        trace_store=trace_store,
        event_bus=event_bus,
        build_eval_comparison=build_eval_comparison,
        eval_case_result_has_provider_issue=eval_case_result_has_provider_issue,
        eval_run_is_degraded=eval_run_is_degraded,
        execute_eval_cases=execute_eval_cases,
        llm_runtime_error_status=llm_runtime_error_status,
        publish_trace_events=_publish_trace_events,
        save_eval_progress=save_eval_progress,
        with_eval_metadata=with_eval_metadata,
    )

    register_chat_routes(
        app,
        trace_store=trace_store,
        event_bus=event_bus,
        require_chat_session=_require_chat_session,
        require_trace=_require_trace,
        run_support_triage_agent=run_support_triage_agent,
        with_chat_metadata=with_chat_metadata,
        publish_trace_events=_publish_trace_events,
        assistant_response_from_trace=assistant_response_from_trace,
        conversation_history=conversation_history,
        start_async_chat_turn=lambda **kwargs: start_async_chat_turn(**kwargs),
    )

    register_workflow_routes(
        app,
        trace_store=trace_store,
        event_bus=event_bus,
        workflow_runs=workflow_runs,
        require_trace=_require_trace,
        run_support_triage_agent=run_support_triage_agent,
        publish_trace_events=_publish_trace_events,
    )

    register_trace_routes(
        app,
        trace_store=trace_store,
        event_bus=event_bus,
        require_trace=_require_trace,
        publish_trace_events=_publish_trace_events,
        update_approval_span=update_approval_span,
    )

    return app


def _database_path() -> Path:
    return Path(os.environ.get("AGENTTRACE_DB", str(DEFAULT_DB_PATH)))


def _require_trace(store: SQLiteTraceStore, trace_id: str) -> Trace:
    trace = store.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
    return trace


def _require_chat_session(store: SQLiteTraceStore, session_id: str) -> dict[str, Any]:
    session = store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Chat session not found: {session_id}")
    return session


def _publish_trace_events(event_bus: EventBus, event_type: str, trace_id: str, **extra: Any) -> None:
    event_bus.publish(event_type, resource_type="trace", resource_id=trace_id, trace_id=trace_id, **extra)
    event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")


app = create_app()
