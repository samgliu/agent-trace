"""Eval-run helpers for API route handlers."""

from __future__ import annotations

import re
from typing import Any, cast

from agenttrace.api.event_bus import EventBus
from agenttrace.core.models import Trace
from agenttrace.evals.support_triage import (
    SUPPORT_TRIAGE_EVAL_CASES,
    EvalExecutionMode,
    eval_check_category,
    run_support_triage_eval_case,
)
from agenttrace.storage.sqlite import SQLiteTraceStore


def with_eval_metadata(
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


def build_eval_comparison(
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
    if eval_run_is_degraded(llm):
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


def build_eval_failure_trends(
    store: SQLiteTraceStore,
    *,
    suite_id: str,
    limit: int = 20,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    summaries = store.list_eval_runs(limit=100, offset=0)["items"]
    selected_summaries = [
        summary
        for summary in summaries
        if summary["suite_id"] == suite_id and (execution_mode is None or summary["execution_mode"] == execution_mode)
    ][:limit]
    runs = [run for summary in selected_summaries if (run := store.get_eval_run(summary["run_id"])) is not None]
    runs.reverse()

    categories = ["Routing", "Evidence", "Governance", "Response", "Memory", "Reliability", "Other"]
    totals = {category: 0 for category in categories}
    points: list[dict[str, Any]] = []
    for index, run in enumerate(runs, start=1):
        failed_by_category = {category: 0 for category in categories}
        failed_check_count = 0
        for result in run.get("results", []):
            for check in result.get("checks", []):
                if not isinstance(check, dict) or check.get("passed"):
                    continue
                category = eval_check_category(str(check.get("name") or ""))
                failed_by_category[category] = failed_by_category.get(category, 0) + 1
                totals[category] = totals.get(category, 0) + 1
                failed_check_count += 1
        points.append(
            {
                "run_id": run["run_id"],
                "label": f"Run {index}",
                "created_at": run["created_at"],
                "execution_mode": run["execution_mode"],
                "model_provider": run["model_provider"],
                "model_name": run["model_name"],
                "status": run["status"],
                "pass_rate": run["pass_rate"],
                "failed_cases": run["failed"],
                "failed_checks": failed_check_count,
                "categories": failed_by_category,
            }
        )

    return {
        "suite_id": suite_id,
        "limit": limit,
        "execution_mode": execution_mode,
        "categories": categories,
        "totals": totals,
        "points": points,
    }


def eval_run_is_degraded(run: dict[str, Any]) -> bool:
    return run.get("status") == "degraded" or is_degraded_provider_error(str(run.get("error") or ""))


def eval_case_result_has_provider_issue(result: dict[str, Any]) -> bool:
    for event in result.get("model_events") or []:
        if not isinstance(event, dict):
            continue
        if is_degraded_provider_error(str(event.get("error") or "")):
            return True
        for attempt in event.get("attempts") or []:
            if isinstance(attempt, dict) and is_degraded_provider_error(str(attempt.get("error") or "")):
                return True
    return any(
        is_degraded_provider_error(str(check.get("actual") or ""))
        or is_degraded_provider_error(str(check.get("expected") or ""))
        for check in result.get("checks") or []
        if isinstance(check, dict)
    )


def is_degraded_provider_error(message: str) -> bool:
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


def execute_eval_cases(
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
            trace = with_eval_metadata(
                case_result.trace,
                suite_id="support-triage-core",
                case_id=case.case_id,
                execution_mode=execution_mode,
                model_provider=model_provider,
                model_name=model_name,
            )
            store.save_trace(trace)
            publish_trace_events(event_bus, "trace.created", trace.trace_id)
            results.append(case_result.to_dict())
            save_eval_progress(
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
            status = "degraded" if is_degraded_provider_error(str(exc)) else "failed"
            save_eval_progress(
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
    save_eval_progress(
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


def save_eval_progress(
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


def llm_runtime_error_status(message: str) -> int:
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


def publish_trace_events(event_bus: EventBus, event_type: str, trace_id: str, **extra: Any) -> None:
    event_bus.publish(event_type, resource_type="trace", resource_id=trace_id, trace_id=trace_id, **extra)
    event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")


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
