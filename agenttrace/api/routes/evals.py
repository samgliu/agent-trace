"""Eval route registration."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable, cast

from fastapi import FastAPI, HTTPException, Query

from agenttrace.api.event_bus import EventBus
from agenttrace.core.models import Trace
from agenttrace.evals.support_triage import (
    SUPPORT_TRIAGE_EVAL_CASES,
    EvalExecutionMode,
    eval_model_metadata,
    list_support_triage_eval_suites,
    run_support_triage_eval_suite,
)
from agenttrace.storage.sqlite import SQLiteTraceStore

BuildEvalComparison = Callable[..., dict[str, Any]]
BuildEvalFailureTrends = Callable[..., dict[str, Any]]
ExecuteEvalCases = Callable[..., None]
LlmRuntimeErrorStatus = Callable[[str], int]
PublishTraceEvents = Callable[..., None]
SaveEvalProgress = Callable[..., dict[str, Any]]
WithEvalMetadata = Callable[..., Trace]
EvalRunPredicate = Callable[[dict[str, Any]], bool]


def register_eval_routes(
    app: FastAPI,
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    build_eval_comparison: BuildEvalComparison,
    build_eval_failure_trends: BuildEvalFailureTrends,
    eval_case_result_has_provider_issue: EvalRunPredicate,
    eval_run_is_degraded: EvalRunPredicate,
    execute_eval_cases: ExecuteEvalCases,
    llm_runtime_error_status: LlmRuntimeErrorStatus,
    publish_trace_events: PublishTraceEvents,
    save_eval_progress: SaveEvalProgress,
    with_eval_metadata: WithEvalMetadata,
) -> None:
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
        return build_eval_comparison(suite_id="support-triage-core", deterministic=deterministic, llm=llm)

    @app.get("/eval-runs/support-triage/failure-trends")
    def get_support_triage_eval_failure_trends(
        limit: int = Query(20, ge=1, le=100),
        mode: str | None = Query(None, pattern="^(deterministic|llm)$"),
    ) -> dict[str, Any]:
        return build_eval_failure_trends(
            trace_store,
            suite_id="support-triage-core",
            limit=limit,
            execution_mode=mode,
        )

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
            raise HTTPException(status_code=llm_runtime_error_status(str(exc)), detail=str(exc)) from exc
        for case_result in result.results:
            trace = with_eval_metadata(
                case_result.trace,
                suite_id=result.suite_id,
                case_id=case_result.case.case_id,
                execution_mode=result.execution_mode,
                model_provider=result.model_provider,
                model_name=result.model_name,
            )
            trace_store.save_trace(trace)
            publish_trace_events(event_bus, "trace.created", trace.trace_id)
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
            raise HTTPException(status_code=llm_runtime_error_status(str(exc)), detail=str(exc)) from exc
        run = save_eval_progress(
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
            execute_eval_cases(
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
        if not eval_run_is_degraded(run):
            raise HTTPException(status_code=400, detail=f"Eval run is not degraded: {run_id}")
        retry_case_ids = {
            result["case_id"]
            for result in run.get("results", [])
            if eval_case_result_has_provider_issue(result)
        }
        preserved_results = [
            result for result in run.get("results", []) if result["case_id"] not in retry_case_ids
        ]
        preserved_case_ids = {result["case_id"] for result in preserved_results}
        remaining_cases = [
            case
            for case in SUPPORT_TRIAGE_EVAL_CASES
            if case.case_id not in preserved_case_ids
        ]
        if not remaining_cases:
            raise HTTPException(status_code=400, detail=f"Eval run has no incomplete or retryable cases: {run_id}")
        running = save_eval_progress(
            trace_store,
            run_id=run_id,
            created_at=run["created_at"],
            execution_mode=run["execution_mode"],
            model_provider=run["model_provider"],
            model_name=run["model_name"],
            status="running",
            results=preserved_results,
        )
        event_bus.publish("eval_run.updated", resource_type="eval_run", resource_id=run_id, run_id=run_id)

        def execute() -> None:
            execute_eval_cases(
                trace_store,
                event_bus,
                run_id=run_id,
                created_at=run["created_at"],
                execution_mode=run["execution_mode"],
                model_provider=run["model_provider"],
                model_name=run["model_name"],
                openai_api=openai_api,
                results=preserved_results,
                cases=remaining_cases,
            )

        thread = threading.Thread(target=execute, name=f"agenttrace-eval-resume-{run_id}", daemon=True)
        thread.start()
        return running


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
