"""Deterministic eval suite for the support-triage workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agenttrace.agents.support_triage import SupportTriageRunner, build_default_runner
from agenttrace.core.models import Trace
from agenttrace.core.summary import build_trace_summary

SUITE_ID = "support-triage-core"
SUITE_NAME = "Support triage core"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    message: str
    customer_email: str
    expected_trace_status: str
    expected_issue_type: str | None = None
    expected_action_type: str | None = None
    expected_approval_required: bool | None = None
    expected_grounding_status: str | None = None
    expected_memory_warning_count: int | None = None
    expected_error_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "message": self.message,
            "customer_email": self.customer_email,
        }


@dataclass(frozen=True)
class EvalCheck:
    name: str
    expected: Any
    actual: Any
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class EvalCaseResult:
    case: EvalCase
    trace: Trace
    checks: list[EvalCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        passed_count = sum(1 for check in self.checks if check.passed)
        return round(passed_count / len(self.checks), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "name": self.case.name,
            "trace_id": self.trace.trace_id,
            "passed": self.passed,
            "score": self.score,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class EvalSuiteResult:
    suite_id: str
    name: str
    results: list[EvalCaseResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.passed / self.total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "results": [result.to_dict() for result in self.results],
        }


SUPPORT_TRIAGE_EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        case_id="duplicate-charge-refund",
        name="Duplicate charge refund",
        message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
        customer_email="customer@example.com",
        expected_trace_status="passed",
        expected_issue_type="billing_duplicate_charge",
        expected_action_type="refund_review",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
    ),
    EvalCase(
        case_id="annual-refund-approval",
        name="Annual refund needs approval",
        message="Can you refund my annual plan?",
        customer_email="annual@example.com",
        expected_trace_status="recovered",
        expected_issue_type="annual_plan_refund",
        expected_action_type="refund_review",
        expected_approval_required=True,
        expected_grounding_status="recovered",
        expected_memory_warning_count=0,
        expected_error_count=0,
    ),
    EvalCase(
        case_id="unknown-customer-clarification",
        name="Unknown customer clarification",
        message="Can you help with my account?",
        customer_email="unknown@example.com",
        expected_trace_status="passed",
        expected_issue_type="general_support",
        expected_action_type="clarification_request",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=3,
        expected_error_count=0,
    ),
    EvalCase(
        case_id="lookup-timeout-failure",
        name="Lookup timeout failure",
        message="I cannot access my account after upgrading.",
        customer_email="timeout@example.com",
        expected_trace_status="failed",
        expected_issue_type="account_access",
        expected_error_count=1,
    ),
)


def list_support_triage_eval_suites() -> list[dict[str, Any]]:
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
    runner_factory: Callable[[], SupportTriageRunner] | None = None,
    trace_id_prefix: str = "trace_eval_support_triage",
) -> EvalSuiteResult:
    make_runner = runner_factory or (lambda: build_default_runner(use_openai=False))
    results = [
        _run_eval_case(case, runner=make_runner(), trace_id=f"{trace_id_prefix}_{case.case_id.replace('-', '_')}")
        for case in SUPPORT_TRIAGE_EVAL_CASES
    ]
    return EvalSuiteResult(suite_id=SUITE_ID, name=SUITE_NAME, results=results)


def _run_eval_case(case: EvalCase, *, runner: SupportTriageRunner, trace_id: str) -> EvalCaseResult:
    trace = runner.run(message=case.message, customer_email=case.customer_email, trace_id=trace_id)
    actual = _actual_values(trace)
    checks = [
        _check("trace_status", case.expected_trace_status, trace.status),
    ]
    if case.expected_issue_type is not None:
        checks.append(_check("issue_type", case.expected_issue_type, actual["issue_type"]))
    if case.expected_action_type is not None:
        checks.append(_check("action_type", case.expected_action_type, actual["action_type"]))
    if case.expected_approval_required is not None:
        checks.append(_check("approval_required", case.expected_approval_required, actual["approval_required"]))
    if case.expected_grounding_status is not None:
        checks.append(_check("grounding_status", case.expected_grounding_status, actual["grounding_status"]))
    if case.expected_memory_warning_count is not None:
        checks.append(_check("memory_warning_count", case.expected_memory_warning_count, actual["memory_warning_count"]))
    if case.expected_error_count is not None:
        checks.append(_check("error_count", case.expected_error_count, actual["error_count"]))
    return EvalCaseResult(case=case, trace=trace, checks=checks)


def _actual_values(trace: Trace) -> dict[str, Any]:
    triage_span = _find_span(trace, "Triage Agent")
    action_span = _find_span(trace, "Action Agent")
    validator_span = _find_span(trace, "Validator Agent")
    summary = build_trace_summary(trace)
    return {
        "issue_type": _dict_value(triage_span.output if triage_span else None, "issue_type"),
        "action_type": _dict_value(action_span.output if action_span else None, "action_type"),
        "approval_required": _dict_value(validator_span.output if validator_span else None, "approval_required"),
        "grounding_status": _dict_value(validator_span.output if validator_span else None, "grounding_status"),
        "memory_warning_count": summary["memory_warning_count"],
        "error_count": summary["error_count"],
    }


def _find_span(trace: Trace, name: str):
    return next((span for span in trace.spans if span.name == name), None)


def _dict_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _check(name: str, expected: Any, actual: Any) -> EvalCheck:
    return EvalCheck(name=name, expected=expected, actual=actual, passed=actual == expected)
