"""Eval suite for the support-triage workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from agent_apps.customer_service.runner import SupportTriageRunner, build_default_runner, resolve_model_config
from agenttrace.core.models import Trace
from agenttrace.core.summary import build_trace_summary

SUITE_ID = "support-triage-core"
SUITE_NAME = "Support triage core"
EvalExecutionMode = Literal["deterministic", "llm"]


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
    expected_next_required_step: str | None = None
    expected_missing_fields: tuple[str, ...] = ()
    expected_risk_signals: tuple[str, ...] = ()
    expected_approval_reason_contains: str | None = None
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
            "model_events": _model_events(self.trace),
        }


@dataclass(frozen=True)
class EvalSuiteResult:
    suite_id: str
    name: str
    results: list[EvalCaseResult]
    execution_mode: EvalExecutionMode = "deterministic"
    model_provider: str = "static"
    model_name: str = "deterministic"

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
            "execution_mode": self.execution_mode,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "results": [result.to_dict() for result in self.results],
        }


def build_eval_report(result: EvalSuiteResult) -> dict[str, Any]:
    failed_cases = []
    category_counts: dict[str, int] = {}
    for case_result in result.results:
        failed_checks = [check for check in case_result.checks if not check.passed]
        if not failed_checks:
            continue
        failed_cases.append(
            {
                "case_id": case_result.case.case_id,
                "name": case_result.case.name,
                "trace_id": case_result.trace.trace_id,
                "score": case_result.score,
                "failed_checks": [check.to_dict() for check in failed_checks],
            }
        )
        for check in failed_checks:
            category = eval_check_category(check.name)
            category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "suite_id": result.suite_id,
        "name": result.name,
        "execution_mode": result.execution_mode,
        "model_provider": result.model_provider,
        "model_name": result.model_name,
        "status": "passed" if result.failed == 0 else "failed",
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "pass_rate": result.pass_rate,
        "failed_cases": failed_cases,
        "failed_check_categories": category_counts,
        "improvement_plan": build_improvement_plan(failed_cases, category_counts),
    }


def build_improvement_plan(failed_cases: list[dict[str, Any]], category_counts: dict[str, int]) -> list[dict[str, Any]]:
    if not failed_cases:
        return []
    cases_by_category: dict[str, list[dict[str, Any]]] = {}
    for case in failed_cases:
        for check in case["failed_checks"]:
            category = eval_check_category(check["name"])
            cases_by_category.setdefault(category, []).append(
                {
                    "case_id": case["case_id"],
                    "trace_id": case["trace_id"],
                    "check": check["name"],
                    "expected": check["expected"],
                    "actual": check["actual"],
                }
            )

    return [
        {
            "category": category,
            "failed_check_count": category_counts[category],
            "owner_area": _improvement_owner_area(category),
            "recommended_action": _improvement_recommended_action(category),
            "suggested_files": _improvement_suggested_files(category),
            "cases": cases_by_category.get(category, []),
        }
        for category in sorted(category_counts, key=lambda item: (-category_counts[item], item))
    ]


def format_eval_report(report: dict[str, Any]) -> str:
    lines = [
        f"Eval suite: {report['name']} ({report['suite_id']})",
        f"Mode: {report['execution_mode']} ({report['model_provider']}/{report['model_name']})",
        f"Status: {report['status']}",
        f"Cases: {report['passed']}/{report['total']} passed",
        f"Pass rate: {report['pass_rate']:.1%}",
    ]
    failed_cases = report.get("failed_cases", [])
    if not failed_cases:
        lines.append("Failed cases: none")
        return "\n".join(lines)

    lines.append("Failed cases:")
    for case in failed_cases:
        lines.append(f"- {case['case_id']} ({case['score']:.1%}) trace={case['trace_id']}")
        for check in case["failed_checks"]:
            lines.append(f"  - {check['name']}: expected {check['expected']}, got {check['actual']}")
    categories = report.get("failed_check_categories") or {}
    if categories:
        lines.append("Failed check categories:")
        for category, count in sorted(categories.items()):
            lines.append(f"- {category}: {count}")
    improvement_plan = report.get("improvement_plan") or []
    if improvement_plan:
        lines.append("Improvement workflow:")
        lines.append("1. Open each listed trace and inspect Agent Flow, failed spans, model output, and evidence.")
        lines.append("2. Patch the smallest prompt, policy, domain, or guardrail surface that explains the failure.")
        lines.append("3. Add or update a focused eval/test for the case before rerunning deterministic and LLM evals.")
        for item in improvement_plan:
            files = ", ".join(item["suggested_files"])
            lines.append(f"- {item['category']} ({item['failed_check_count']}): {item['recommended_action']}")
            lines.append(f"  owner={item['owner_area']} files={files}")
    return "\n".join(lines)


def eval_check_category(name: str) -> str:
    if name in {"trace_status", "error_count"}:
        return "Reliability"
    if name in {"issue_type", "policy_id", "action_type"}:
        return "Routing"
    if name.startswith("tool_used") or name.startswith("evidence_id") or name.startswith("agent_state"):
        return "Evidence"
    if name == "approval_required" or name == "approval_reason":
        return "Governance"
    if name == "grounding_status" or name.startswith("response_"):
        return "Response"
    if name.startswith("memory_"):
        return "Memory"
    return "Other"


def _improvement_owner_area(category: str) -> str:
    return {
        "Routing": "multi-agent routing and policy/action planning",
        "Evidence": "tool usage, memory state, and evidence propagation",
        "Governance": "approval policy and validator guardrails",
        "Response": "customer-facing response generation and grounding",
        "Memory": "short-term continuity and long-term customer memory",
        "Reliability": "tool failure handling and workflow recovery",
    }.get(category, "support-triage workflow")


def _improvement_recommended_action(category: str) -> str:
    return {
        "Routing": "tighten triage, policy retrieval, or action prompts so the selected issue/policy/action matches the request.",
        "Evidence": "verify required tool calls and carry evidence ids into agent state, validation, and final action output.",
        "Governance": "align validator approval decisions and approval reasons with policy requirements.",
        "Response": "adjust response instructions so the answer contains required facts and avoids prohibited claims.",
        "Memory": "preserve active issue state across turns and avoid topic drift unless the customer clearly switches topic.",
        "Reliability": "make failure paths explicit and ensure tool errors become recovered or failed traces as expected.",
    }.get(category, "inspect the failed trace and add the smallest targeted regression check.")


def _improvement_suggested_files(category: str) -> list[str]:
    common = ["agent_apps/customer_service/runner.py", "agenttrace/evals/support_triage.py"]
    extra = {
        "Routing": ["agent_apps/customer_service/domain.py"],
        "Evidence": ["agent_apps/customer_service/domain.py"],
        "Governance": ["agent_apps/customer_service/domain.py"],
        "Response": [],
        "Memory": ["agent_apps/customer_service/domain.py"],
        "Reliability": ["agent_apps/customer_service/domain.py", "agenttrace/mcp_tools/tools.py"],
    }.get(category, [])
    return [*common, *extra]


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
        expected_next_required_step="create_support_action",
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
        expected_tool_names=("lookup_subscription_tool",),
        expected_evidence_ids=("sub_annual_800",),
        expected_next_required_step="human_approval",
        expected_approval_reason_contains="Policy requires human approval.",
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
        expected_tool_names=("lookup_subscription_tool",),
        expected_evidence_ids=("sub_cus_123_pro",),
        expected_next_required_step="human_approval",
        expected_approval_reason_contains="Policy requires human approval.",
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
        expected_next_required_step="collect_missing_information",
        expected_missing_fields=("verified_email",),
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
        expected_next_required_step="collect_missing_information",
        expected_missing_fields=("order_number_or_receipt", "product_issue_reason"),
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
        expected_next_required_step="create_support_action",
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
        expected_next_required_step="create_support_action",
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
        expected_next_required_step="create_support_action",
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
        expected_next_required_step="human_review",
        expected_risk_signals=("high_prior_refund_count", "recent_chargebacks", "unverified_payment_method", "new_account"),
        expected_approval_reason_contains="Human review required by abuse-risk controls.",
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
        expected_tool_names=("verify_account_access_tool",),
        expected_evidence_ids=("account_access_mismatch",),
        expected_next_required_step="collect_missing_information",
        expected_missing_fields=("verified_account_ownership", "matching_order_or_subscription_owner"),
        expected_risk_signals=("requested_resource_belongs_to_different_account",),
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
    if case.expected_next_required_step is not None:
        checks.append(_check("agent_state.next_required_step", case.expected_next_required_step, actual["agent_state"].get("next_required_step")))
    for field in case.expected_missing_fields:
        checks.append(_includes_check(f"agent_state.missing_field:{field}", actual["agent_state"].get("missing_fields", []), field))
    for signal in case.expected_risk_signals:
        checks.append(_includes_check(f"agent_state.risk_signal:{signal}", actual["agent_state"].get("risk_signals", []), signal))
    if case.expected_approval_reason_contains is not None:
        checks.append(_contains_check("approval_reason", actual["approval_reason"], case.expected_approval_reason_contains))
    return EvalCaseResult(case=case, trace=trace, checks=checks)


def _model_events(trace: Trace) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for span in trace.spans:
        model = span.span_data.get("model")
        attempts = span.span_data.get("model_attempts")
        fallback_used = span.span_data.get("model_fallback_used")
        if not model and not attempts and not fallback_used:
            continue
        event: dict[str, Any] = {
            "span_name": span.name,
            "model": model if isinstance(model, str) else None,
            "fallback_used": fallback_used if isinstance(fallback_used, bool) else False,
        }
        if isinstance(attempts, list):
            event["attempts"] = attempts
        events.append(event)
    return events


def _actual_values(trace: Trace) -> dict[str, Any]:
    triage_span = _find_span(trace, "Triage Agent")
    retrieval_span = _find_span(trace, "retrieve_policy")
    action_span = _find_span(trace, "Action Agent")
    validator_span = _find_span(trace, "Validator Agent")
    response_span = _find_span(trace, "Customer Response Generator")
    approval_span = _find_span(trace, "Human Approval Gate")
    state_span = _find_span(trace, "Update Agent State") or _find_span(trace, "Write Working Memory")
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
        "approval_reason": _dict_value(approval_span.output if approval_span else None, "reason") or "",
        "agent_state": _agent_state_from_span(state_span),
        "tool_names": _tool_names(trace),
        "evidence_ids": _evidence_ids(trace),
    }


def _find_span(trace: Trace, name: str):
    return next((span for span in trace.spans if span.name == name), None)


def _dict_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _agent_state_from_span(span: Any) -> dict[str, Any]:
    output = span.output if span else None
    if isinstance(output, dict) and isinstance(output.get("agent_state"), dict):
        return output["agent_state"]
    return {}


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
