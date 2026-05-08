"""AgentTrace API application."""

from __future__ import annotations

import os
import time
import threading
import uuid
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agenttrace.api.schemas import (
    ChatMessageCreateRequest,
    ChatSessionCreateRequest,
    SpanIngestRequest,
    SupportTriageRunRequest,
    TraceIngestRequest,
    TraceLifecycleUpdateRequest,
)
from agenttrace.agents.support_triage import build_default_runner
from agenttrace.adapters.openai_agents import normalize_openai_agents_trace
from agenttrace.core.grounding import build_grounding_summary
from agenttrace.core.importer import normalize_trace
from agenttrace.core.metrics import build_trace_metrics
from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agenttrace.core.summary import build_dashboard_summary
from agenttrace.evals.support_triage import list_support_triage_eval_suites, run_support_triage_eval_suite
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
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )
    trace_store = store or SQLiteTraceStore(_database_path())
    trace_store.initialize()
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
                    "runner": "agenttrace.agents.support_triage",
                    "live_run": True,
                },
            ),
            source_format="agenttrace",
            source_kind="agent_runner",
        )
        trace_store.upsert_trace(placeholder)
        run = workflow_runs.create(
            live_trace_id,
            input_data={
                "message": payload.message,
                "customer_email": payload.customer_email,
                "use_openai": payload.use_openai,
                "openai_api": payload.openai_api,
            },
        )
        span_delay_seconds = _live_span_delay_seconds()

        def execute() -> None:
            workflow_runs.mark_running(run["run_id"])
            try:
                def persist_span(span: Span) -> None:
                    if workflow_runs.is_cancel_requested(run["run_id"]):
                        raise WorkflowRunCancelled("Workflow run cancelled.")
                    trace_store.upsert_span(span)
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
            except WorkflowRunCancelled as exc:
                trace_store.update_trace_lifecycle(live_trace_id, status="cancelled", ended_at=_utc_now())
                workflow_runs.mark_cancelled(run["run_id"], str(exc))
            except RuntimeError as exc:
                trace_store.update_trace_lifecycle(live_trace_id, status="failed", ended_at=_utc_now())
                workflow_runs.mark_failed(run["run_id"], str(exc))
            except Exception as exc:  # pragma: no cover - defensive for background execution.
                trace_store.update_trace_lifecycle(live_trace_id, status="failed", ended_at=_utc_now())
                workflow_runs.mark_failed(run["run_id"], f"Unexpected workflow failure: {exc}")

        thread = threading.Thread(target=execute, name=f"agenttrace-run-{run['run_id']}", daemon=True)
        thread.start()
        saved_run = workflow_runs.get(run["run_id"]) or run
        return {**saved_run, "trace": _require_trace(trace_store, live_trace_id).to_dict()}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

    @app.get("/eval-runs/{run_id}")
    def get_eval_run(run_id: str) -> dict[str, Any]:
        run = trace_store.get_eval_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")
        return run

    @app.post("/evals/support-triage/run")
    def run_support_triage_evals() -> dict[str, Any]:
        result = run_support_triage_eval_suite()
        for case_result in result.results:
            trace = _with_eval_metadata(case_result.trace, suite_id=result.suite_id, case_id=case_result.case.case_id)
            trace_store.save_trace(trace)
        return trace_store.save_eval_run(result.to_dict())

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
        user_message = trace_store.add_chat_message(
            session_id,
            role="user",
            content=payload.content,
        )
        try:
            trace = build_default_runner(use_openai=payload.use_openai, openai_api=payload.openai_api).run(
                message=payload.content,
                customer_email=session["customer_email"],
                trace_id=f"trace_chat_{user_message['message_id']}",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        trace = _with_chat_metadata(trace, session_id=session_id, user_message_id=user_message["message_id"])
        trace_store.save_trace(trace)
        saved_trace = _require_trace(trace_store, trace.trace_id)
        assistant_message = trace_store.add_chat_message(
            session_id,
            role="assistant",
            content=_assistant_response_from_trace(saved_trace),
            trace_id=saved_trace.trace_id,
            metadata={"trace_status": saved_trace.status},
        )
        return {
            "session": _require_chat_session(trace_store, session_id),
            "user_message": user_message,
            "assistant_message": assistant_message,
            "trace": saved_trace.to_dict(),
        }

    @app.post("/workflows/support-triage/runs")
    def run_support_triage_workflow(payload: SupportTriageRunRequest) -> dict[str, Any]:
        try:
            trace = build_default_runner(use_openai=payload.use_openai, openai_api=payload.openai_api).run(
                message=payload.message,
                customer_email=payload.customer_email,
                trace_id=payload.trace_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        trace_store.save_trace(trace)
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
        saved = _require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/ingest/openai-agents")
    def ingest_openai_agents_trace(payload: dict[str, Any]) -> dict[str, Any]:
        trace = normalize_openai_agents_trace(payload)
        trace_store.upsert_trace(trace)
        for span in trace.spans:
            trace_store.upsert_span(span)
        saved = _require_trace(trace_store, trace.trace_id)
        return saved.to_dict()

    @app.post("/traces/{trace_id}/spans")
    def ingest_span(trace_id: str, payload: SpanIngestRequest) -> dict[str, Any]:
        _require_trace(trace_store, trace_id)
        span = Span.from_dict({**payload.model_dump(), "trace_id": trace_id}, trace_id=trace_id)
        return trace_store.upsert_span(span).to_dict()

    @app.patch("/traces/{trace_id}")
    def update_trace(trace_id: str, payload: TraceLifecycleUpdateRequest) -> dict[str, Any]:
        updated = trace_store.update_trace_lifecycle(
            trace_id,
            status=payload.status,
            ended_at=payload.ended_at,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
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


def _with_eval_metadata(trace: Trace, *, suite_id: str, case_id: str) -> Trace:
    metadata = {
        **trace.metadata,
        "eval_suite_id": suite_id,
        "eval_case_id": case_id,
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
