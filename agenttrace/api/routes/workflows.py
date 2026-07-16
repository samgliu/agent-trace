"""Workflow route registration and workflow run state."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException

from agent_apps.customer_service.runner import build_default_runner
from agenttrace.api.event_bus import EventBus
from agenttrace.api.schemas import SupportTriageRunRequest
from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agenttrace.storage.sqlite import SQLiteTraceStore

RunSupportTriageAgent = Callable[..., Trace]
RequireTrace = Callable[[SQLiteTraceStore, str], Trace]
PublishTraceEvents = Callable[..., None]


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


class WorkflowRunCancelled(RuntimeError):
    pass


def reconcile_stale_workflow_runs(store: SQLiteTraceStore, workflow_runs: WorkflowRunRegistry) -> None:
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


def register_workflow_routes(
    app: FastAPI,
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    workflow_runs: WorkflowRunRegistry,
    require_trace: RequireTrace,
    run_support_triage_agent: RunSupportTriageAgent,
    publish_trace_events: PublishTraceEvents,
) -> None:
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
        publish_trace_events(event_bus, "trace.created", live_trace_id)
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
                    publish_trace_events(event_bus, "span.updated", span.trace_id, span_id=span.span_id)
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
                publish_trace_events(event_bus, "trace.updated", trace.trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.completed", run["run_id"], trace_id=trace.trace_id)
            except WorkflowRunCancelled as exc:
                trace_store.update_trace_lifecycle(live_trace_id, status="cancelled", ended_at=_utc_now())
                workflow_runs.mark_cancelled(run["run_id"], str(exc))
                publish_trace_events(event_bus, "trace.updated", live_trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.cancelled", run["run_id"], trace_id=live_trace_id)
            except RuntimeError as exc:
                trace_store.update_trace_lifecycle(live_trace_id, status="failed", ended_at=_utc_now())
                workflow_runs.mark_failed(run["run_id"], str(exc))
                publish_trace_events(event_bus, "trace.updated", live_trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.failed", run["run_id"], trace_id=live_trace_id)
            except Exception as exc:  # pragma: no cover - defensive for background execution.
                trace_store.update_trace_lifecycle(live_trace_id, status="failed", ended_at=_utc_now())
                workflow_runs.mark_failed(run["run_id"], f"Unexpected workflow failure: {exc}")
                publish_trace_events(event_bus, "trace.updated", live_trace_id)
                _publish_workflow_run_event(event_bus, "workflow_run.failed", run["run_id"], trace_id=live_trace_id)

        thread = threading.Thread(target=execute, name=f"agenttrace-run-{run['run_id']}", daemon=True)
        thread.start()
        saved_run = workflow_runs.get(run["run_id"]) or run
        return {**saved_run, "trace": require_trace(trace_store, live_trace_id).to_dict()}

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
        except RuntimeError as exc:
            raise _http_exception_from_runtime_error(exc) from exc
        trace_store.save_trace(trace)
        publish_trace_events(event_bus, "trace.created", trace.trace_id)
        saved = require_trace(trace_store, trace.trace_id)
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
            publish_trace_events(event_bus, "trace.updated", run["trace_id"])
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


def _publish_workflow_run_event(event_bus: EventBus, event_type: str, run_id: str, *, trace_id: str | None) -> None:
    event_bus.publish(event_type, resource_type="workflow_run", resource_id=run_id, run_id=run_id, trace_id=trace_id)


def _live_span_delay_seconds() -> float:
    raw_value = os.environ.get("AGENTTRACE_LIVE_SPAN_DELAY_SECONDS", "0.15")
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return 0.15


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_exception_from_runtime_error(exc: RuntimeError) -> HTTPException:
    return HTTPException(
        status_code=int(getattr(exc, "status_code", 400)),
        detail=str(getattr(exc, "message", str(exc))),
    )
