"""AgentTrace API application."""

from __future__ import annotations

import os
import re
import time
import threading
import uuid
import json
import queue
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agenttrace.api.schemas import (
    ChatMessageCreateRequest,
    ChatSessionCreateRequest,
    SpanIngestRequest,
    SupportTriageRunRequest,
    TraceIngestRequest,
    TraceLifecycleUpdateRequest,
)
from agent_apps.customer_service.runner import build_default_runner
from agenttrace.adapters.openai_agents import normalize_openai_agents_trace
from agenttrace.core.grounding import build_grounding_summary
from agenttrace.core.importer import normalize_trace
from agenttrace.core.metrics import build_trace_metrics
from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agenttrace.core.summary import build_dashboard_summary
from agenttrace.evals.support_triage import (
    SUPPORT_TRIAGE_EVAL_CASES,
    EvalExecutionMode,
    eval_model_metadata,
    list_support_triage_eval_suites,
    run_support_triage_eval_case,
    run_support_triage_eval_suite,
)
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
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )
    trace_store = store or SQLiteTraceStore(_database_path())
    trace_store.initialize()
    event_bus = EventBus()
    workflow_runs = WorkflowRunRegistry(trace_store)
    _reconcile_stale_workflow_runs(trace_store, workflow_runs)

    def launch_live_support_triage(payload: SupportTriageRunRequest, trace_id: str | None = None) -> dict[str, Any]:
        live_trace_id = trace_id or payload.trace_id or f"trace_support_triage_{uuid.uuid4().hex[:12]}"
        placeholder = with_source_metadata(
            Trace(
                trace_id=live_trace_id,
                workflow_name="support-triage",
                status="running",
                started_at=datetime.now(timezone.utc),
                metadata={
                    "source": "agenttrace-agent-runner",
                    "runner": "agent_apps.customer_service.runner",
                    "live_run": True,
                },
            ),
            source_format="agenttrace",
            source_kind="agent_runner",
        )
        trace_store.upsert_trace(placeholder)
        _publish_trace_events(event_bus, "trace.created", live_trace_id)
        run = workflow_runs.create(
            live_trace_id,
            input_data={
                "message": payload.message,
                "customer_email": payload.customer_email,
                "use_openai": payload.use_openai,
                "openai_api": payload.openai_api,
            },
        )
        _publish_workflow_run_event(event_bus, "workflow_run.created", run["run_id"], trace_id=live_trace_id)
        span_delay_seconds = _live_span_delay_seconds()

        def execute() -> None:
            workflow_runs.mark_running(run["run_id"])
            _publish_workflow_run_event(event_bus, "workflow_run.updated", run["run_id"], trace_id=live_trace_id)
            try:
                def persist_span(span: Span) -> None:
                    if workflow_runs.is_cancel_requested(run["run_id"]):
                        raise WorkflowRunCancelled("Workflow run cancelled.")
                    trace_store.upsert_span(span)
                    _publish_trace_events(event_bus, "span.updated", span.trace_id, span_id=span.span_id)
                    if span_delay_seconds > 0:
                        time.sleep(span_delay_seconds)

                trace = build_default_runner(use_openai=payload.use_openai, openai_api=payload.openai_api).run(
                    message=payload.message,
                    customer_email=payload.customer_email,
                    trace_id=live_trace_id,
                    on_span=persist_span,
                )
                if workflow_runs.is_cancel_requested(run["run_id"]):
                    raise WorkflowRunCancelled("Workflow run cancelled.")
                trace_store.save_trace(trace)
                workflow_runs.mark_completed(run["run_id"], trace.trace_id)
                _publish_trace_events(event_bus, "trace.updated", trace.trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.completed", run["run_id"], trace_id=trace.trace_id)
            except WorkflowRunCancelled as exc:
                trace_store.update_trace_lifecycle(live_trace_id, status="cancelled", ended_at=_utc_now())
                workflow_runs.mark_cancelled(run["run_id"], str(exc))
                _publish_trace_events(event_bus, "trace.updated", live_trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.cancelled", run["run_id"], trace_id=live_trace_id)
            except RuntimeError as exc:
                trace_store.update_trace_lifecycle(live_trace_id, status="failed", ended_at=_utc_now())
                workflow_runs.mark_failed(run["run_id"], str(exc))
                _publish_trace_events(event_bus, "trace.updated", live_trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.failed", run["run_id"], trace_id=live_trace_id)
            except Exception as exc:  # pragma: no cover - defensive for background execution.
                trace_store.update_trace_lifecycle(live_trace_id, status="failed", ended_at=_utc_now())
                workflow_runs.mark_failed(run["run_id"], f"Unexpected workflow failure: {exc}")
                _publish_trace_events(event_bus, "trace.updated", live_trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.failed", run["run_id"], trace_id=live_trace_id)

        thread = threading.Thread(target=execute, name=f"agenttrace-run-{run['run_id']}", daemon=True)
        thread.start()
        saved_run = workflow_runs.get(run["run_id"]) or run
        return {**saved_run, "trace": _require_trace(trace_store, live_trace_id).to_dict()}

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

    @app.get("/evals")
    def list_evals() -> dict[str, Any]:
        return {"suites": list_support_triage_eval_suites()}

    @app.get("/eval-runs")
    def list_eval_runs(limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        return trace_store.list_eval_runs(limit=limit, offset=offset)

    @app.get("/eval-runs/support-triage/comparison")
    def get_support_triage_eval_comparison() -> dict[str, Any]:
        deterministic = trace_store.get_latest_eval_run(suite_id="support-triage-core", execution_mode="deterministic")
        llm = trace_store.get_latest_eval_run(suite_id="support-triage-core", execution_mode="llm")
        return _build_eval_comparison(suite_id="support-triage-core", deterministic=deterministic, llm=llm)

    @app.get("/eval-runs/{run_id}")
    def get_eval_run(run_id: str) -> dict[str, Any]:
        run = trace_store.get_eval_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")
        return run

    @app.post("/evals/support-triage/run")
    def run_support_triage_evals(
        mode: str = Query("deterministic", pattern="^(deterministic|llm)$"),
        openai_api: str = Query("chat_completions", pattern="^(chat_completions|responses)$"),
    ) -> dict[str, Any]:
        try:
            result = run_support_triage_eval_suite(execution_mode=cast(EvalExecutionMode, mode), openai_api=openai_api)
        except RuntimeError as exc:
            raise HTTPException(status_code=_llm_runtime_error_status(str(exc)), detail=str(exc)) from exc
        for case_result in result.results:
            trace = _with_eval_metadata(
                case_result.trace,
                suite_id=result.suite_id,
                case_id=case_result.case.case_id,
                execution_mode=result.execution_mode,
                model_provider=result.model_provider,
                model_name=result.model_name,
            )
            trace_store.save_trace(trace)
            _publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = trace_store.save_eval_run(result.to_dict())
        event_bus.publish("eval_run.completed", resource_type="eval_run", resource_id=saved["run_id"])
        event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")
        return saved

    @app.post("/evals/support-triage/run/async")
    def start_support_triage_eval_run(
        mode: str = Query("llm", pattern="^(deterministic|llm)$"),
        openai_api: str = Query("chat_completions", pattern="^(chat_completions|responses)$"),
    ) -> dict[str, Any]:
        execution_mode = cast(EvalExecutionMode, mode)
        run_id = f"eval_{uuid.uuid4().hex[:12]}"
        created_at = _utc_now()
        try:
            model_provider, model_name = eval_model_metadata(execution_mode=execution_mode)
        except RuntimeError as exc:
            raise HTTPException(status_code=_llm_runtime_error_status(str(exc)), detail=str(exc)) from exc
        run = _save_eval_progress(
            trace_store,
            run_id=run_id,
            created_at=created_at,
            execution_mode=execution_mode,
            model_provider=model_provider,
            model_name=model_name,
            status="running",
            results=[],
        )
        event_bus.publish("eval_run.created", resource_type="eval_run", resource_id=run_id, run_id=run_id)

        def execute() -> None:
            _execute_eval_cases(
                trace_store,
                event_bus,
                run_id=run_id,
                created_at=created_at,
                execution_mode=execution_mode,
                model_provider=model_provider,
                model_name=model_name,
                openai_api=openai_api,
                results=[],
                cases=list(SUPPORT_TRIAGE_EVAL_CASES),
            )

        thread = threading.Thread(target=execute, name=f"agenttrace-eval-{run_id}", daemon=True)
        thread.start()
        return run

    @app.post("/eval-runs/{run_id}/resume")
    def resume_eval_run(
        run_id: str,
        openai_api: str = Query("chat_completions", pattern="^(chat_completions|responses)$"),
    ) -> dict[str, Any]:
        run = trace_store.get_eval_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")
        if run["execution_mode"] != "llm":
            raise HTTPException(status_code=400, detail="Only LLM-backed eval runs can be resumed.")
        if not _eval_run_is_degraded(run):
            raise HTTPException(status_code=400, detail=f"Eval run is not degraded: {run_id}")
        completed_case_ids = {result["case_id"] for result in run.get("results", [])}
        remaining_cases = [case for case in SUPPORT_TRIAGE_EVAL_CASES if case.case_id not in completed_case_ids]
        if not remaining_cases:
            raise HTTPException(status_code=400, detail=f"Eval run has no incomplete cases: {run_id}")
        running = _save_eval_progress(
            trace_store,
            run_id=run_id,
            created_at=run["created_at"],
            execution_mode=run["execution_mode"],
            model_provider=run["model_provider"],
            model_name=run["model_name"],
            status="running",
            results=list(run.get("results", [])),
        )
        event_bus.publish("eval_run.updated", resource_type="eval_run", resource_id=run_id, run_id=run_id)

        def execute() -> None:
            _execute_eval_cases(
                trace_store,
                event_bus,
                run_id=run_id,
                created_at=run["created_at"],
                execution_mode=run["execution_mode"],
                model_provider=run["model_provider"],
                model_name=run["model_name"],
                openai_api=openai_api,
                results=list(run.get("results", [])),
                cases=remaining_cases,
            )

        thread = threading.Thread(target=execute, name=f"agenttrace-eval-resume-{run_id}", daemon=True)
        thread.start()
        return running

    @app.post("/chat/sessions")
    def create_chat_session(payload: ChatSessionCreateRequest) -> dict[str, Any]:
        session = trace_store.create_chat_session(
            customer_email=payload.customer_email,
            title=payload.title,
            metadata=payload.metadata,
        )
        return {**session, "messages": []}

    @app.get("/chat/sessions")
    def list_chat_sessions() -> list[dict[str, Any]]:
        return trace_store.list_chat_sessions()

    @app.get("/chat/sessions/{session_id}")
    def get_chat_session(session_id: str) -> dict[str, Any]:
        session = _require_chat_session(trace_store, session_id)
        return {**session, "messages": trace_store.list_chat_messages(session_id)}

    @app.get("/chat/sessions/{session_id}/messages")
    def list_chat_messages(session_id: str) -> list[dict[str, Any]]:
        _require_chat_session(trace_store, session_id)
        return trace_store.list_chat_messages(session_id)

    @app.post("/chat/sessions/{session_id}/messages")
    def create_chat_message(session_id: str, payload: ChatMessageCreateRequest) -> dict[str, Any]:
        session = _require_chat_session(trace_store, session_id)
        previous_messages = trace_store.list_chat_messages(session_id)
        user_message = trace_store.add_chat_message(
            session_id,
            role="user",
            content=payload.content,
        )
        conversation_history = _conversation_history(previous_messages)
        try:
            trace = run_support_triage_agent(
                message=payload.content,
                customer_email=session["customer_email"],
                trace_id=f"trace_chat_{user_message['message_id']}",
                conversation_history=conversation_history,
                use_openai=payload.use_openai,
                openai_api=payload.openai_api,
            )
        except AgentServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        trace = _with_chat_metadata(trace, session_id=session_id, user_message_id=user_message["message_id"])
        trace_store.save_trace(trace)
        _publish_trace_events(event_bus, "trace.created", trace.trace_id, session_id=session_id)
        saved_trace = _require_trace(trace_store, trace.trace_id)
        assistant_message = trace_store.add_chat_message(
            session_id,
            role="assistant",
            content=_assistant_response_from_trace(saved_trace),
            trace_id=saved_trace.trace_id,
            metadata={"trace_status": saved_trace.status},
        )
        event_bus.publish("chat.turn.completed", resource_type="chat_session", resource_id=session_id, session_id=session_id, trace_id=saved_trace.trace_id)
        return {
            "session": _require_chat_session(trace_store, session_id),
            "user_message": user_message,
            "assistant_message": assistant_message,
            "trace": saved_trace.to_dict(),
        }

    @app.post("/chat/sessions/{session_id}/messages/async")
    def create_async_chat_message(session_id: str, payload: ChatMessageCreateRequest) -> dict[str, Any]:
        session = _require_chat_session(trace_store, session_id)
        previous_messages = trace_store.list_chat_messages(session_id)
        user_message = trace_store.add_chat_message(
            session_id,
            role="user",
            content=payload.content,
        )
        assistant_message = trace_store.add_chat_message(
            session_id,
            role="assistant",
            content="Checking account, policy, and approval context",
            metadata={
                "status": "pending",
                "pending": True,
                "chat_user_message_id": user_message["message_id"],
            },
        )
        event_bus.publish(
            "chat.turn.started",
            resource_type="chat_session",
            resource_id=session_id,
            session_id=session_id,
        )
        _start_async_chat_turn(
            trace_store=trace_store,
            event_bus=event_bus,
            session=session,
            previous_messages=previous_messages,
            user_message=user_message,
            assistant_message=assistant_message,
            payload=payload,
        )
        return {
            "session": _require_chat_session(trace_store, session_id),
            "user_message": user_message,
            "assistant_message": assistant_message,
        }

    @app.post("/workflows/support-triage/runs")
    def run_support_triage_workflow(payload: SupportTriageRunRequest) -> dict[str, Any]:
        try:
            trace = run_support_triage_agent(
                message=payload.message,
                customer_email=payload.customer_email,
                trace_id=payload.trace_id,
                use_openai=payload.use_openai,
                openai_api=payload.openai_api,
            )
        except AgentServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        trace_store.save_trace(trace)
        _publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = _require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/workflows/support-triage/runs/live")
    def start_live_support_triage_workflow(payload: SupportTriageRunRequest) -> dict[str, Any]:
        return launch_live_support_triage(payload)

    @app.get("/workflow-runs/{run_id}")
    def get_workflow_run(run_id: str) -> dict[str, Any]:
        run = workflow_runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Workflow run not found: {run_id}")
        payload = dict(run)
        if run["trace_id"]:
            trace = trace_store.get_trace(run["trace_id"])
            if trace is not None:
                payload["trace"] = trace.to_dict()
        return payload

    @app.post("/workflow-runs/{run_id}/cancel")
    def cancel_workflow_run(run_id: str) -> dict[str, Any]:
        run = workflow_runs.request_cancel(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Workflow run not found: {run_id}")
        if run["status"] == "cancelled" and run["trace_id"]:
            trace_store.update_trace_lifecycle(run["trace_id"], status="cancelled", ended_at=_utc_now())
            _publish_trace_events(event_bus, "trace.updated", run["trace_id"])
        _publish_workflow_run_event(event_bus, "workflow_run.updated", run_id, trace_id=run["trace_id"])
        return get_workflow_run(run_id)

    @app.post("/workflow-runs/{run_id}/retry")
    def retry_workflow_run(run_id: str) -> dict[str, Any]:
        run = workflow_runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Workflow run not found: {run_id}")
        if run["status"] in {"pending", "running", "cancel_requested"}:
            raise HTTPException(status_code=400, detail=f"Workflow run is still active: {run_id}")
        input_data = run.get("input") or {}
        if not input_data:
            raise HTTPException(status_code=400, detail=f"Workflow run cannot be retried: {run_id}")
        retry_payload = SupportTriageRunRequest(
            message=str(input_data["message"]),
            customer_email=str(input_data["customer_email"]),
            use_openai=bool(input_data.get("use_openai", False)),
            openai_api=input_data.get("openai_api", "chat_completions"),
        )
        return launch_live_support_triage(retry_payload, trace_id=f"{run['trace_id']}_retry_{uuid.uuid4().hex[:6]}")

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
        _publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = _require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/ingest/openai-agents")
    def ingest_openai_agents_trace(payload: dict[str, Any]) -> dict[str, Any]:
        trace = normalize_openai_agents_trace(payload)
        trace_store.upsert_trace(trace)
        for span in trace.spans:
            trace_store.upsert_span(span)
        _publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = _require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/traces/{trace_id}/spans")
    def ingest_span(trace_id: str, payload: SpanIngestRequest) -> dict[str, Any]:
        _require_trace(trace_store, trace_id)
        span = Span.from_dict({**payload.model_dump(), "trace_id": trace_id}, trace_id=trace_id)
        saved = trace_store.upsert_span(span)
        _publish_trace_events(event_bus, "span.updated", trace_id, span_id=saved.span_id)
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
        _publish_trace_events(event_bus, "trace.updated", trace_id)
        return updated.to_dict()

    @app.get("/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        trace = _require_trace(trace_store, trace_id)
        return trace.to_dict()

    @app.get("/traces/{trace_id}/raw")
    def get_raw_trace(trace_id: str) -> dict[str, Any] | list[Any]:
        trace = _require_trace(trace_store, trace_id)
        return trace.raw_payload or trace.to_dict()

    @app.get("/traces/{trace_id}/spans")
    def get_spans(trace_id: str) -> list[dict[str, Any]]:
        trace = _require_trace(trace_store, trace_id)
        return [span.to_dict() for span in trace.spans]

    @app.get("/traces/{trace_id}/metrics")
    def get_metrics(trace_id: str) -> dict[str, Any]:
        trace = _require_trace(trace_store, trace_id)
        return build_trace_metrics(trace)

    @app.get("/traces/{trace_id}/grounding")
    def get_grounding(trace_id: str) -> dict[str, Any]:
        trace = _require_trace(trace_store, trace_id)
        return build_grounding_summary(trace)

    @app.post("/traces/{trace_id}/approvals/{span_id}/approve")
    def approve_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return _update_approval_span(trace_store, trace_id, span_id, "approved", event_bus=event_bus).to_dict()

    @app.post("/traces/{trace_id}/approvals/{span_id}/reject")
    def reject_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return _update_approval_span(trace_store, trace_id, span_id, "rejected", event_bus=event_bus).to_dict()

    @app.post("/traces/{trace_id}/approvals/{span_id}/revert")
    def revert_span(trace_id: str, span_id: str) -> dict[str, Any]:
        return _update_approval_span(trace_store, trace_id, span_id, "blocked", event_bus=event_bus).to_dict()

    return app


def _database_path() -> Path:
    return Path(os.environ.get("AGENTTRACE_DB", str(DEFAULT_DB_PATH)))


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type,
            "created_at": _utc_now(),
            **payload,
        }
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
        return event

    def stream(self):
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        try:
            yield _sse_frame({"type": "connected"}, event_type="connected")
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield _sse_frame(event, event_type=event["type"])
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)


def _sse_frame(payload: dict[str, Any], *, event_type: str) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


class AgentServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def run_support_triage_agent(
    *,
    message: str,
    customer_email: str,
    trace_id: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    use_openai: bool = False,
    openai_api: str = "chat_completions",
) -> Trace:
    agent_service_url = _agent_service_url()
    if agent_service_url:
        return _run_support_triage_via_agent_service(
            agent_service_url=agent_service_url,
            message=message,
            customer_email=customer_email,
            trace_id=trace_id,
            conversation_history=conversation_history or [],
            use_openai=use_openai,
            openai_api=openai_api,
        )
    return build_default_runner(use_openai=use_openai, openai_api=openai_api).run(
        message=message,
        customer_email=customer_email,
        trace_id=trace_id,
        conversation_history=conversation_history,
    )


def _agent_service_url() -> str | None:
    raw_value = os.environ.get("AGENTTRACE_AGENT_SERVICE_URL", "").strip()
    return raw_value.rstrip("/") if raw_value else None


def _run_support_triage_via_agent_service(
    *,
    agent_service_url: str,
    message: str,
    customer_email: str,
    trace_id: str | None,
    conversation_history: list[dict[str, Any]],
    use_openai: bool,
    openai_api: str,
) -> Trace:
    payload = {
        "message": message,
        "customer_email": customer_email,
        "trace_id": trace_id,
        "conversation_history": conversation_history,
        "use_openai": use_openai,
        "openai_api": openai_api,
    }
    response = _post_agent_service_json(f"{agent_service_url}/runs/support-triage", payload)
    trace_payload = response.get("trace")
    if not isinstance(trace_payload, dict):
        raise AgentServiceError("Agent service returned an invalid trace payload.", status_code=502)
    return Trace.from_dict(trace_payload)


def _post_agent_service_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_agent_service_timeout_seconds()) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = _agent_service_error_message(exc)
        raise AgentServiceError(message, status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise AgentServiceError(f"Agent service is unavailable: {exc.reason}", status_code=502) from exc
    except TimeoutError as exc:
        raise AgentServiceError("Agent service timed out while running the workflow.", status_code=504) from exc
    if not isinstance(parsed, dict):
        raise AgentServiceError("Agent service returned an invalid JSON payload.", status_code=502)
    return parsed


def _agent_service_timeout_seconds() -> float:
    raw_value = os.environ.get("AGENTTRACE_AGENT_SERVICE_TIMEOUT_SECONDS", "300")
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return 300.0


def _agent_service_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return f"Agent service request failed with HTTP {exc.code}."
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    return f"Agent service request failed with HTTP {exc.code}."


def _with_eval_metadata(
    trace: Trace,
    *,
    suite_id: str,
    case_id: str,
    execution_mode: str,
    model_provider: str,
    model_name: str,
) -> Trace:
    metadata = {
        **trace.metadata,
        "eval_suite_id": suite_id,
        "eval_case_id": case_id,
        "eval_execution_mode": execution_mode,
        "model_provider": model_provider,
        "model_name": model_name,
        "source_kind": "eval_run",
    }
    return Trace(
        trace_id=trace.trace_id,
        workflow_name=trace.workflow_name,
        group_id=trace.group_id,
        status=trace.status,
        metadata=metadata,
        raw_payload=trace.raw_payload,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        spans=trace.spans,
    )


def _build_eval_comparison(
    *,
    suite_id: str,
    deterministic: dict[str, Any] | None,
    llm: dict[str, Any] | None,
) -> dict[str, Any]:
    if deterministic is None and llm is None:
        status = "missing_runs"
    elif deterministic is None:
        status = "missing_deterministic"
    elif llm is None:
        status = "missing_llm"
    else:
        status = "ready"

    comparison: dict[str, Any] = {
        "suite_id": suite_id,
        "status": status,
        "deterministic_run": _eval_run_summary(deterministic),
        "llm_run": _eval_run_summary(llm),
        "pass_rate_delta": None,
        "llm_regressions": [],
        "llm_improvements": [],
        "both_failed": [],
    }
    if deterministic is None or llm is None:
        return comparison
    if _eval_run_is_degraded(llm):
        comparison["status"] = "degraded_llm"
        return comparison

    comparison["pass_rate_delta"] = round(llm["pass_rate"] - deterministic["pass_rate"], 4)
    deterministic_cases = {case["case_id"]: case for case in deterministic.get("results", [])}
    for llm_case in llm.get("results", []):
        baseline_case = deterministic_cases.get(llm_case["case_id"])
        if baseline_case is None:
            continue
        case_summary = {
            "case_id": llm_case["case_id"],
            "name": llm_case["name"],
            "deterministic_trace_id": baseline_case["trace_id"],
            "llm_trace_id": llm_case["trace_id"],
            "deterministic_score": baseline_case["score"],
            "llm_score": llm_case["score"],
            "failed_checks": [check for check in llm_case.get("checks", []) if not check.get("passed")],
        }
        if baseline_case["passed"] and not llm_case["passed"]:
            comparison["llm_regressions"].append(case_summary)
        elif not baseline_case["passed"] and llm_case["passed"]:
            comparison["llm_improvements"].append(case_summary)
        elif not baseline_case["passed"] and not llm_case["passed"]:
            comparison["both_failed"].append(case_summary)
    return comparison


def _eval_run_summary(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run["run_id"],
        "suite_id": run["suite_id"],
        "name": run["name"],
        "execution_mode": run["execution_mode"],
        "model_provider": run["model_provider"],
        "model_name": run["model_name"],
        "status": run["status"],
        "error": run.get("error"),
        "total": run["total"],
        "passed": run["passed"],
        "failed": run["failed"],
        "pass_rate": run["pass_rate"],
        "created_at": run["created_at"],
    }


def _eval_run_is_degraded(run: dict[str, Any]) -> bool:
    return run.get("status") == "degraded" or _is_degraded_provider_error(str(run.get("error") or ""))


def _is_degraded_provider_error(message: str) -> bool:
    lowered = message.lower()
    if "http 429" in lowered or "http 503" in lowered or "http 504" in lowered or "http 529" in lowered:
        return True
    return any(
        marker in lowered
        for marker in (
            "resource_exhausted",
            "unavailable",
            "quota exceeded",
            "rate limit",
            "high demand",
            "timed out",
            "timeout",
        )
    )


def _execute_eval_cases(
    store: SQLiteTraceStore,
    event_bus: EventBus,
    *,
    run_id: str,
    created_at: str,
    execution_mode: str,
    model_provider: str,
    model_name: str,
    openai_api: str,
    results: list[dict[str, Any]],
    cases: list[Any],
) -> None:
    status = "running"
    for case in cases:
        try:
            case_result = run_support_triage_eval_case(
                case,
                execution_mode=cast(EvalExecutionMode, execution_mode),
                openai_api=openai_api,
            )
            trace = _with_eval_metadata(
                case_result.trace,
                suite_id="support-triage-core",
                case_id=case.case_id,
                execution_mode=execution_mode,
                model_provider=model_provider,
                model_name=model_name,
            )
            store.save_trace(trace)
            _publish_trace_events(event_bus, "trace.created", trace.trace_id)
            results.append(case_result.to_dict())
            _save_eval_progress(
                store,
                run_id=run_id,
                created_at=created_at,
                execution_mode=execution_mode,
                model_provider=model_provider,
                model_name=model_name,
                status=status,
                results=results,
            )
            event_bus.publish("eval_run.updated", resource_type="eval_run", resource_id=run_id, run_id=run_id)
        except RuntimeError as exc:
            status = "degraded" if _is_degraded_provider_error(str(exc)) else "failed"
            _save_eval_progress(
                store,
                run_id=run_id,
                created_at=created_at,
                execution_mode=execution_mode,
                model_provider=model_provider,
                model_name=model_name,
                status=status,
                results=results,
                error=str(exc),
            )
            event_bus.publish("eval_run.failed", resource_type="eval_run", resource_id=run_id, run_id=run_id)
            event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")
            return
    status = "passed" if all(result["passed"] for result in results) else "failed"
    _save_eval_progress(
        store,
        run_id=run_id,
        created_at=created_at,
        execution_mode=execution_mode,
        model_provider=model_provider,
        model_name=model_name,
        status=status,
        results=results,
    )
    event_bus.publish("eval_run.completed", resource_type="eval_run", resource_id=run_id, run_id=run_id)
    event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")


def _save_eval_progress(
    store: SQLiteTraceStore,
    *,
    run_id: str,
    created_at: str,
    execution_mode: str,
    model_provider: str,
    model_name: str,
    status: str,
    results: list[dict[str, Any]],
    error: str | None = None,
) -> dict[str, Any]:
    passed = sum(1 for result in results if result.get("passed"))
    completed = len(results)
    total = len(SUPPORT_TRIAGE_EVAL_CASES)
    failed = sum(1 for result in results if not result.get("passed")) if status in {"running", "degraded"} else total - passed
    pass_rate_denominator = completed if status in {"running", "degraded"} else total
    return store.save_eval_run(
        {
            "suite_id": "support-triage-core",
            "name": "Support triage core",
            "execution_mode": execution_mode,
            "model_provider": model_provider,
            "model_name": model_name,
            "status": status,
            "error": error,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / pass_rate_denominator, 4) if pass_rate_denominator else 0.0,
            "created_at": created_at,
            "results": [dict(result) for result in results],
        },
        run_id=run_id,
    )


def _llm_runtime_error_status(message: str) -> int:
    if "missing API key" in message or "API key is required" in message or "not configured" in message:
        return 400
    match = re.search(r"HTTP (\d{3})", message)
    if match is None:
        return 502
    upstream_status = int(match.group(1))
    if upstream_status == 429:
        return 429
    if upstream_status in {500, 502, 503, 504, 529}:
        return 502 if upstream_status == 500 else upstream_status
    if 400 <= upstream_status < 500:
        return upstream_status
    return 502


class WorkflowRunRegistry:
    def __init__(self, store: SQLiteTraceStore) -> None:
        self.store = store
        self._lock = threading.Lock()

    def create(self, trace_id: str | None, *, input_data: dict[str, Any]) -> dict[str, Any]:
        return self.store.create_workflow_run(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            workflow_name="support-triage",
            trace_id=trace_id,
            input_data=input_data,
        )

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get_workflow_run(run_id)

    def mark_running(self, run_id: str) -> None:
        self._update(run_id, status="running")

    def mark_completed(self, run_id: str, trace_id: str) -> None:
        self._update(run_id, status="completed", trace_id=trace_id, completed_at=_utc_now())

    def mark_failed(self, run_id: str, error: str) -> None:
        self._update(run_id, status="failed", error=error, completed_at=_utc_now())

    def request_cancel(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self.store.get_workflow_run(run_id)
            if run is None:
                return None
            if run["status"] in {"completed", "failed", "cancelled"}:
                return dict(run)
            return self.store.update_workflow_run(run_id, status="cancel_requested", cancel_requested=True)

    def is_cancel_requested(self, run_id: str) -> bool:
        run = self.store.get_workflow_run(run_id)
        return bool(run and run.get("cancel_requested"))

    def mark_cancelled(self, run_id: str, message: str) -> None:
        self._update(run_id, status="cancelled", error=message, completed_at=_utc_now(), cancel_requested=True)

    def _update(self, run_id: str, **updates: Any) -> None:
        self.store.update_workflow_run(run_id, **updates)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _live_span_delay_seconds() -> float:
    raw_value = os.environ.get("AGENTTRACE_LIVE_SPAN_DELAY_SECONDS", "0.15")
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return 0.15


class WorkflowRunCancelled(RuntimeError):
    pass


def _reconcile_stale_workflow_runs(store: SQLiteTraceStore, workflow_runs: WorkflowRunRegistry) -> None:
    for run in store.list_active_workflow_runs():
        trace_id = run["trace_id"]
        if run["status"] == "cancel_requested":
            if trace_id:
                store.update_trace_lifecycle(trace_id, status="cancelled", ended_at=_utc_now())
            workflow_runs.mark_cancelled(run["run_id"], "Workflow run cancelled during API startup reconciliation.")
            continue
        if trace_id:
            store.update_trace_lifecycle(trace_id, status="failed", ended_at=_utc_now())
        workflow_runs.mark_failed(run["run_id"], "API restarted before workflow completed.")


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


def _publish_workflow_run_event(event_bus: EventBus, event_type: str, run_id: str, *, trace_id: str | None) -> None:
    event_bus.publish(event_type, resource_type="workflow_run", resource_id=run_id, run_id=run_id, trace_id=trace_id)


def _publish_chat_event(
    event_bus: EventBus,
    event_type: str,
    session_id: str,
    message_id: str,
    *,
    trace_id: str | None = None,
) -> None:
    event_bus.publish(
        event_type,
        resource_type="chat_message",
        resource_id=message_id,
        session_id=session_id,
        message_id=message_id,
        trace_id=trace_id,
    )


def _start_async_chat_turn(
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    session: dict[str, Any],
    previous_messages: list[dict[str, Any]],
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    payload: ChatMessageCreateRequest,
) -> None:
    thread = threading.Thread(
        target=_complete_async_chat_turn,
        kwargs={
            "trace_store": trace_store,
            "event_bus": event_bus,
            "session": session,
            "previous_messages": previous_messages,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "payload": payload,
        },
        daemon=True,
    )
    thread.start()


def _complete_async_chat_turn(
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    session: dict[str, Any],
    previous_messages: list[dict[str, Any]],
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    payload: ChatMessageCreateRequest,
) -> None:
    try:
        trace = run_support_triage_agent(
            message=payload.content,
            customer_email=session["customer_email"],
            trace_id=f"trace_chat_{user_message['message_id']}",
            conversation_history=_conversation_history(previous_messages),
            use_openai=payload.use_openai,
            openai_api=payload.openai_api,
        )
        trace = _with_chat_metadata(trace, session_id=session["session_id"], user_message_id=user_message["message_id"])
        trace_store.save_trace(trace)
        _publish_trace_events(event_bus, "trace.created", trace.trace_id, session_id=session["session_id"])
        saved_trace = _require_trace(trace_store, trace.trace_id)
        trace_store.update_chat_message(
            assistant_message["message_id"],
            content=_assistant_response_from_trace(saved_trace),
            trace_id=saved_trace.trace_id,
            metadata={
                "status": "complete",
                "pending": False,
                "trace_status": saved_trace.status,
                "chat_user_message_id": user_message["message_id"],
            },
        )
        event_bus.publish(
            "chat.turn.completed",
            resource_type="chat_session",
            resource_id=session["session_id"],
            session_id=session["session_id"],
            trace_id=saved_trace.trace_id,
        )
    except AgentServiceError as exc:
        _mark_async_chat_failed(trace_store, event_bus, session, assistant_message, user_message, exc.message)
    except RuntimeError as exc:
        _mark_async_chat_failed(trace_store, event_bus, session, assistant_message, user_message, str(exc))


def _mark_async_chat_failed(
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    session: dict[str, Any],
    assistant_message: dict[str, Any],
    user_message: dict[str, Any],
    message: str,
) -> None:
    trace_store.update_chat_message(
        assistant_message["message_id"],
        content=message,
        metadata={
            "status": "failed",
            "pending": False,
            "error": message,
            "chat_user_message_id": user_message["message_id"],
        },
    )
    event_bus.publish(
        "chat.turn.failed",
        resource_type="chat_session",
        resource_id=session["session_id"],
        session_id=session["session_id"],
        message=message,
    )


def _with_chat_metadata(trace: Trace, *, session_id: str, user_message_id: str) -> Trace:
    metadata = dict(trace.metadata)
    metadata["chat_session_id"] = session_id
    metadata["chat_user_message_id"] = user_message_id
    return Trace(
        trace_id=trace.trace_id,
        workflow_name=trace.workflow_name,
        group_id=trace.group_id,
        status=trace.status,
        metadata=metadata,
        raw_payload=trace.raw_payload,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        spans=trace.spans,
    )


def _conversation_history(messages: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    recent = messages[-limit:]
    return [
        {
            "role": message["role"],
            "content": message["content"],
            "trace_id": message.get("trace_id"),
            "event_type": message.get("metadata", {}).get("event_type"),
        }
        for message in recent
    ]


def _assistant_response_from_trace(trace: Trace) -> str:
    for span in reversed(trace.spans):
        if span.span_type != "generation":
            continue
        if isinstance(span.output, dict) and span.output.get("response"):
            return str(span.output["response"])
    if trace.status == "failed":
        return "I could not complete that support workflow. A support specialist should review this request."
    return "I reviewed the request and created the next support action."


def _update_approval_span(
    store: SQLiteTraceStore,
    trace_id: str,
    span_id: str,
    status: str,
    *,
    event_bus: EventBus | None = None,
):
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


app = create_app()
