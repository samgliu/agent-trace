"""Deterministic eval suite for the support-triage workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent_apps.customer_service.runner import SupportTriageRunner, build_default_runner
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
    conversation_history: tuple[dict[str, Any], ...] = ()
    expected_issue_type: str | None = None
    expected_policy_id: str | None = None
    expected_action_type: str | None = None
    expected_approval_required: bool | None = None
    expected_grounding_status: str | None = None
    expected_memory_warning_count: int | None = None
    expected_error_count: int | None = None
    expected_tool_names: tuple[str, ...] = ()
    expected_evidence_ids: tuple[str, ...] = ()
    expected_response_contains: tuple[str, ...] = ()
    expected_response_excludes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "message": self.message,
            "customer_email": self.customer_email,
            "turn_count": len(self.conversation_history) + 1,
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
        expected_policy_id="policy_refund_duplicate_charge",
        expected_action_type="refund_review",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_tool_names=("create_refund_review_tool",),
        expected_evidence_ids=("cus_123", "policy_refund_duplicate_charge"),
    ),
    EvalCase(
        case_id="annual-refund-approval",
        name="Annual refund needs approval",
        message="Can you refund my annual plan?",
        customer_email="annual@example.com",
        expected_trace_status="recovered",
        expected_issue_type="annual_plan_refund",
        expected_policy_id="policy_annual_refund",
        expected_action_type="refund_review",
        expected_approval_required=True,
        expected_grounding_status="recovered",
        expected_memory_warning_count=0,
        expected_error_count=0,
    ),
    EvalCase(
        case_id="stale-subscription-refund-approval",
        name="Stale subscription refund needs approval",
        message="I want a refund on my Prime subscription that was billed 3 years ago. Can I get a refund?",
        customer_email="customer@example.com",
        expected_trace_status="recovered",
        expected_issue_type="stale_subscription_refund",
        expected_policy_id="policy_stale_subscription_refund",
        expected_action_type="refund_review",
        expected_approval_required=True,
        expected_grounding_status="recovered",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_response_excludes=("duplicate charge", "$20"),
    ),
    EvalCase(
        case_id="unknown-customer-clarification",
        name="Unknown customer clarification",
        message="Can you help with my account?",
        customer_email="unknown@example.com",
        expected_trace_status="passed",
        expected_issue_type="general_support",
        expected_policy_id="policy_general_support",
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
    EvalCase(
        case_id="consumed-product-return-boundary",
        name="Consumed product return boundary",
        message="I'd like to return the banana I bought last week. I ate all of them already.",
        customer_email="customer@example.com",
        expected_trace_status="passed",
        expected_issue_type="consumed_product_return",
        expected_policy_id="policy_consumed_product_return",
        expected_action_type="clarification_request",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_response_contains=("fully consumed", "quality"),
        expected_response_excludes=("duplicate", "$20"),
    ),
    EvalCase(
        case_id="consumed-product-return-follow-up",
        name="Consumed product return follow-up",
        message="Order number: #1234",
        customer_email="customer@example.com",
        conversation_history=(
            {
                "role": "user",
                "content": "I'd like to return the banana I bought last week. I ate all of them already.",
            },
            {
                "role": "assistant",
                "content": "Please share the order number or receipt and what was wrong.",
            },
        ),
        expected_trace_status="passed",
        expected_issue_type="consumed_product_return",
        expected_policy_id="policy_consumed_product_return",
        expected_action_type="clarification_request",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_tool_names=("lookup_order_tool", "verify_order_owner_tool"),
        expected_evidence_ids=("cus_123", "ord_1234", "order_customer_match"),
        expected_response_contains=("order number", "normal return"),
        expected_response_excludes=("duplicate", "$20"),
    ),
    EvalCase(
        case_id="explicit-topic-switch-to-duplicate-charge",
        name="Explicit topic switch to duplicate charge",
        message="Actually, separate issue: I was charged twice for my Pro subscription yesterday.",
        customer_email="customer@example.com",
        conversation_history=(
            {
                "role": "user",
                "content": "I'd like to return the banana I bought last week. I ate all of them already.",
            },
            {
                "role": "assistant",
                "content": "Please share the order number or receipt and what was wrong.",
            },
        ),
        expected_trace_status="passed",
        expected_issue_type="billing_duplicate_charge",
        expected_policy_id="policy_refund_duplicate_charge",
        expected_action_type="refund_review",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_response_contains=("duplicate",),
    ),
    EvalCase(
        case_id="consumed-product-quality-exception",
        name="Consumed product quality exception",
        message="Order number #1234. The bananas were moldy and unsafe, so I threw them out.",
        customer_email="customer@example.com",
        conversation_history=(
            {
                "role": "user",
                "content": "I'd like to return the banana I bought last week. I ate all of them already.",
            },
            {
                "role": "assistant",
                "content": "Please share the order number or receipt and what was wrong.",
            },
        ),
        expected_trace_status="passed",
        expected_issue_type="consumed_product_return",
        expected_policy_id="policy_consumed_product_return",
        expected_action_type="courtesy_credit",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_tool_names=("lookup_order_tool", "verify_order_owner_tool", "create_quality_exception_review_tool"),
        expected_evidence_ids=("cus_123", "ord_1234", "policy_consumed_product_return"),
        expected_response_contains=("quality", "courtesy credit"),
        expected_response_excludes=("duplicate", "$20"),
    ),
    EvalCase(
        case_id="repeated-refund-abuse-review",
        name="Repeated refund abuse review",
        message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
        customer_email="risk@example.com",
        expected_trace_status="recovered",
        expected_issue_type="billing_duplicate_charge",
        expected_policy_id="policy_refund_duplicate_charge",
        expected_action_type="refund_review",
        expected_approval_required=True,
        expected_grounding_status="recovered",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_response_contains=("review",),
    ),
    EvalCase(
        case_id="account-mismatch-clarification",
        name="Account mismatch clarification",
        message="The order is under my spouse's different email. Can you refund it from this account?",
        customer_email="customer@example.com",
        expected_trace_status="passed",
        expected_issue_type="general_support",
        expected_policy_id="policy_general_support",
        expected_action_type="clarification_request",
        expected_approval_required=False,
        expected_grounding_status="grounded",
        expected_memory_warning_count=0,
        expected_error_count=0,
        expected_response_contains=("account", "detail"),
        expected_response_excludes=("refund review", "duplicate"),
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
    trace = runner.run(
        message=case.message,
        customer_email=case.customer_email,
        trace_id=trace_id,
        conversation_history=list(case.conversation_history),
    )
    actual = _actual_values(trace)
    checks = [
        _check("trace_status", case.expected_trace_status, trace.status),
    ]
    if case.expected_issue_type is not None:
        checks.append(_check("issue_type", case.expected_issue_type, actual["issue_type"]))
    if case.expected_policy_id is not None:
        checks.append(_check("policy_id", case.expected_policy_id, actual["policy_id"]))
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
    for expected_text in case.expected_response_contains:
        checks.append(_contains_check(f"response_contains:{expected_text}", actual["response"], expected_text))
    for rejected_text in case.expected_response_excludes:
        checks.append(_excludes_check(f"response_excludes:{rejected_text}", actual["response"], rejected_text))
    for tool_name in case.expected_tool_names:
        checks.append(_includes_check(f"tool_used:{tool_name}", actual["tool_names"], tool_name))
    for evidence_id in case.expected_evidence_ids:
        checks.append(_includes_check(f"evidence_id:{evidence_id}", actual["evidence_ids"], evidence_id))
    return EvalCaseResult(case=case, trace=trace, checks=checks)


def _actual_values(trace: Trace) -> dict[str, Any]:
    triage_span = _find_span(trace, "Triage Agent")
    retrieval_span = _find_span(trace, "retrieve_policy")
    action_span = _find_span(trace, "Action Agent")
    validator_span = _find_span(trace, "Validator Agent")
    response_span = _find_span(trace, "Customer Response Generator")
    summary = build_trace_summary(trace)
    return {
        "issue_type": _dict_value(triage_span.output if triage_span else None, "issue_type"),
        "policy_id": _dict_value(retrieval_span.output if retrieval_span else None, "policy_id"),
        "action_type": _dict_value(action_span.output if action_span else None, "action_type"),
        "approval_required": _dict_value(validator_span.output if validator_span else None, "approval_required"),
        "grounding_status": _dict_value(validator_span.output if validator_span else None, "grounding_status"),
        "memory_warning_count": summary["memory_warning_count"],
        "error_count": summary["error_count"],
        "response": _dict_value(response_span.output if response_span else None, "response") or "",
        "tool_names": _tool_names(trace),
        "evidence_ids": _evidence_ids(trace),
    }


def _find_span(trace: Trace, name: str):
    return next((span for span in trace.spans if span.name == name), None)


def _dict_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _tool_names(trace: Trace) -> list[str]:
    names: list[str] = []
    for span in trace.spans:
        tool_name = span.span_data.get("tool_name")
        if isinstance(tool_name, str):
            names.append(tool_name)
    return names


def _evidence_ids(trace: Trace) -> list[str]:
    ids: list[str] = []
    for span in trace.spans:
        if isinstance(span.output, dict):
            for key in ("evidence_ids", "evidence"):
                value = span.output.get(key)
                if isinstance(value, list):
                    ids.extend(str(item) for item in value)
            grounding_evidence = span.output.get("grounding_evidence")
            if isinstance(grounding_evidence, list):
                ids.extend(
                    str(item["id"])
                    for item in grounding_evidence
                    if isinstance(item, dict) and item.get("id") is not None
                )
    return list(dict.fromkeys(ids))


def _check(name: str, expected: Any, actual: Any) -> EvalCheck:
    return EvalCheck(name=name, expected=expected, actual=actual, passed=actual == expected)


def _contains_check(name: str, actual: str, expected_text: str) -> EvalCheck:
    return EvalCheck(
        name=name,
        expected=f"contains {expected_text}",
        actual=actual,
        passed=expected_text.lower() in actual.lower(),
    )


def _excludes_check(name: str, actual: str, rejected_text: str) -> EvalCheck:
    return EvalCheck(
        name=name,
        expected=f"excludes {rejected_text}",
        actual=actual,
        passed=rejected_text.lower() not in actual.lower(),
    )


def _includes_check(name: str, actual: list[str], expected_text: str) -> EvalCheck:
    return EvalCheck(
        name=name,
        expected=f"includes {expected_text}",
        actual=actual,
        passed=expected_text in actual,
    )
