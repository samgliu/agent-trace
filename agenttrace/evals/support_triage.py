"""Eval suite orchestration for the support-triage workflow."""

from __future__ import annotations

from typing import Callable

from agent_apps.customer_service.runner import SupportTriageRunner, build_default_runner, resolve_model_config
from agenttrace.evals.models import EvalCase, EvalCaseResult, EvalCheck, EvalExecutionMode, EvalSuiteResult
from agenttrace.evals.reporting import build_eval_report, eval_check_category, format_eval_report
from agenttrace.evals.support_triage_cases import SUPPORT_TRIAGE_EVAL_CASES
from agenttrace.evals.trace_assertions import (
    actual_values as _actual_values,
    check as _check,
    contains_check as _contains_check,
    dict_value as _dict_value,
    evaluate_trace,
    evidence_ids as _evidence_ids,
    excludes_check as _excludes_check,
    find_span as _find_span,
    includes_check as _includes_check,
    model_events as _model_events,
    tool_names as _tool_names,
)

SUITE_ID = "support-triage-core"
SUITE_NAME = "Support triage core"


def list_support_triage_eval_suites() -> list[dict[str, object]]:
    return [
        {
            "suite_id": SUITE_ID,
            "name": SUITE_NAME,
            "workflow_name": "support-triage",
            "case_count": len(SUPPORT_TRIAGE_EVAL_CASES),
            "cases": [case.to_dict() for case in SUPPORT_TRIAGE_EVAL_CASES],
        }
    ]


def run_support_triage_eval_suite(
    *,
    execution_mode: EvalExecutionMode = "deterministic",
    openai_api: str = "chat_completions",
    runner_factory: Callable[[], SupportTriageRunner] | None = None,
    trace_id_prefix: str | None = None,
) -> EvalSuiteResult:
    if execution_mode not in {"deterministic", "llm"}:
        raise ValueError(f"Unsupported eval execution mode: {execution_mode}")
    use_openai = execution_mode == "llm"
    make_runner = runner_factory or (lambda: build_default_runner(use_openai=use_openai, openai_api=openai_api))
    prefix = trace_id_prefix or ("trace_eval_support_triage_llm" if use_openai else "trace_eval_support_triage")
    model_provider, model_name = eval_model_metadata(execution_mode=execution_mode)
    results = [
        _run_eval_case(case, runner=make_runner(), trace_id=f"{prefix}_{case.case_id.replace('-', '_')}")
        for case in SUPPORT_TRIAGE_EVAL_CASES
    ]
    return EvalSuiteResult(
        suite_id=SUITE_ID,
        name=SUITE_NAME,
        results=results,
        execution_mode=execution_mode,
        model_provider=model_provider,
        model_name=model_name,
    )


def eval_model_metadata(*, execution_mode: EvalExecutionMode) -> tuple[str, str]:
    if execution_mode == "deterministic":
        return "static", "deterministic"
    config = resolve_model_config()
    return config.provider, config.model


def run_support_triage_eval_case(
    case: EvalCase,
    *,
    execution_mode: EvalExecutionMode = "deterministic",
    openai_api: str = "chat_completions",
    runner_factory: Callable[[], SupportTriageRunner] | None = None,
    trace_id_prefix: str | None = None,
) -> EvalCaseResult:
    if execution_mode not in {"deterministic", "llm"}:
        raise ValueError(f"Unsupported eval execution mode: {execution_mode}")
    use_openai = execution_mode == "llm"
    make_runner = runner_factory or (lambda: build_default_runner(use_openai=use_openai, openai_api=openai_api))
    prefix = trace_id_prefix or ("trace_eval_support_triage_llm" if use_openai else "trace_eval_support_triage")
    return _run_eval_case(case, runner=make_runner(), trace_id=f"{prefix}_{case.case_id.replace('-', '_')}")


def _run_eval_case(case: EvalCase, *, runner: SupportTriageRunner, trace_id: str) -> EvalCaseResult:
    trace = runner.run(
        message=case.message,
        customer_email=case.customer_email,
        trace_id=trace_id,
        conversation_history=list(case.conversation_history),
    )
    return evaluate_trace(case, trace)


__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalCheck",
    "EvalExecutionMode",
    "EvalSuiteResult",
    "SUPPORT_TRIAGE_EVAL_CASES",
    "build_eval_report",
    "eval_check_category",
    "eval_model_metadata",
    "format_eval_report",
    "list_support_triage_eval_suites",
    "run_support_triage_eval_case",
    "run_support_triage_eval_suite",
]
