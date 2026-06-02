"""Trace extraction and check helpers for evals."""

from __future__ import annotations

from typing import Any

from agenttrace.core.models import Trace
from agenttrace.core.summary import build_trace_summary
from agenttrace.evals.models import EvalCase, EvalCaseResult, EvalCheck


def evaluate_trace(case: EvalCase, trace: Trace) -> EvalCaseResult:
    actual = actual_values(trace)
    checks = [
        check("trace_status", case.expected_trace_status, trace.status),
    ]
    if case.expected_supervisor_route is not None:
        checks.append(check("supervisor_route", case.expected_supervisor_route, actual["supervisor_route"]))
    if case.expected_issue_type is not None:
        checks.append(check("issue_type", case.expected_issue_type, actual["issue_type"]))
    if case.expected_policy_id is not None:
        checks.append(check("policy_id", case.expected_policy_id, actual["policy_id"]))
    if case.expected_action_type is not None:
        checks.append(check("action_type", case.expected_action_type, actual["action_type"]))
    if case.expected_approval_required is not None:
        checks.append(check("approval_required", case.expected_approval_required, actual["approval_required"]))
    if case.expected_grounding_status is not None:
        checks.append(check("grounding_status", case.expected_grounding_status, actual["grounding_status"]))
    if case.expected_memory_warning_count is not None:
        checks.append(check("memory_warning_count", case.expected_memory_warning_count, actual["memory_warning_count"]))
    if case.expected_error_count is not None:
        checks.append(check("error_count", case.expected_error_count, actual["error_count"]))
    for expected_text in case.expected_response_contains:
        checks.append(contains_check(f"response_contains:{expected_text}", actual["response"], expected_text))
    for rejected_text in case.expected_response_excludes:
        checks.append(excludes_check(f"response_excludes:{rejected_text}", actual["response"], rejected_text))
    for tool_name in case.expected_tool_names:
        checks.append(includes_check(f"tool_used:{tool_name}", actual["tool_names"], tool_name))
    for evidence_id in case.expected_evidence_ids:
        checks.append(includes_check(f"evidence_id:{evidence_id}", actual["evidence_ids"], evidence_id))
    if case.expected_next_required_step is not None:
        checks.append(
            check(
                "agent_state.next_required_step",
                case.expected_next_required_step,
                actual["agent_state"].get("next_required_step"),
            )
        )
    for field in case.expected_missing_fields:
        checks.append(includes_check(f"agent_state.missing_field:{field}", actual["agent_state"].get("missing_fields", []), field))
    for signal in case.expected_risk_signals:
        checks.append(includes_check(f"agent_state.risk_signal:{signal}", actual["agent_state"].get("risk_signals", []), signal))
    if case.expected_escalation_type is not None:
        checks.append(check("escalation_type", case.expected_escalation_type, actual["escalation"].get("escalation_type")))
    if case.expected_escalation_owner is not None:
        checks.append(check("escalation_owner", case.expected_escalation_owner, actual["escalation"].get("next_owner")))
    if case.expected_escalation_reason_contains is not None:
        checks.append(
            contains_check(
                "escalation_reason",
                actual["escalation"].get("reason", ""),
                case.expected_escalation_reason_contains,
            )
        )
    if case.expected_approval_reason_contains is not None:
        checks.append(contains_check("approval_reason", actual["approval_reason"], case.expected_approval_reason_contains))
    return EvalCaseResult(case=case, trace=trace, checks=checks)


def model_events(trace: Trace) -> list[dict[str, Any]]:
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


def actual_values(trace: Trace) -> dict[str, Any]:
    supervisor_span = find_span(trace, "Supervisor Agent")
    triage_span = find_span(trace, "Triage Agent")
    retrieval_span = find_span(trace, "retrieve_policy")
    action_span = find_span(trace, "Action Agent")
    validator_span = find_span(trace, "Validator Agent")
    response_span = find_span(trace, "Customer Response Generator")
    approval_span = find_span(trace, "Human Approval Gate")
    escalation_span = find_span(trace, "Escalation Agent")
    state_span = find_span(trace, "Update Agent State") or find_span(trace, "Write Working Memory")
    summary = build_trace_summary(trace)
    return {
        "supervisor_route": dict_value(supervisor_span.output if supervisor_span else None, "route"),
        "issue_type": dict_value(triage_span.output if triage_span else None, "issue_type"),
        "policy_id": dict_value(retrieval_span.output if retrieval_span else None, "policy_id"),
        "action_type": dict_value(action_span.output if action_span else None, "action_type"),
        "approval_required": dict_value(validator_span.output if validator_span else None, "approval_required"),
        "grounding_status": dict_value(validator_span.output if validator_span else None, "grounding_status"),
        "memory_warning_count": summary["memory_warning_count"],
        "error_count": summary["error_count"],
        "response": dict_value(response_span.output if response_span else None, "response") or "",
        "approval_reason": dict_value(approval_span.output if approval_span else None, "reason") or "",
        "escalation": escalation_from_span(escalation_span),
        "agent_state": agent_state_from_span(state_span),
        "tool_names": tool_names(trace),
        "evidence_ids": evidence_ids(trace),
    }


def find_span(trace: Trace, name: str):
    return next((span for span in trace.spans if span.name == name), None)


def dict_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def agent_state_from_span(span: Any) -> dict[str, Any]:
    output = span.output if span else None
    if isinstance(output, dict) and isinstance(output.get("agent_state"), dict):
        return output["agent_state"]
    return {}


def escalation_from_span(span: Any) -> dict[str, Any]:
    output = span.output if span else None
    if isinstance(output, dict):
        return output
    return {}


def tool_names(trace: Trace) -> list[str]:
    names: list[str] = []
    for span in trace.spans:
        tool_name = span.span_data.get("tool_name")
        if isinstance(tool_name, str):
            names.append(tool_name)
    return names


def evidence_ids(trace: Trace) -> list[str]:
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


def check(name: str, expected: Any, actual: Any) -> EvalCheck:
    return EvalCheck(name=name, expected=expected, actual=actual, passed=actual == expected)


def contains_check(name: str, actual: str, expected_text: str) -> EvalCheck:
    return EvalCheck(
        name=name,
        expected=f"contains {expected_text}",
        actual=actual,
        passed=expected_text.lower() in actual.lower(),
    )


def excludes_check(name: str, actual: str, rejected_text: str) -> EvalCheck:
    return EvalCheck(
        name=name,
        expected=f"excludes {rejected_text}",
        actual=actual,
        passed=rejected_text.lower() not in actual.lower(),
    )


def includes_check(name: str, actual: list[str], expected_text: str) -> EvalCheck:
    return EvalCheck(
        name=name,
        expected=f"includes {expected_text}",
        actual=actual,
        passed=expected_text in actual,
    )
