"""Prompt and agent-decision helpers for the customer-service runner."""

from __future__ import annotations

import json
from typing import Any

from agent_apps.customer_service.model_client import LLMResponse

PROMPT_VERSION = "support-triage-v2"


def supervisor_instructions() -> str:
    return (
        "You are the Supervisor Agent in a customer-service multi-agent workflow. "
        "Return only JSON with route and handoff_reason. Use standard_support when the customer states an "
        "order, billing, refund, subscription, return, or account issue that needs specialist investigation. "
        "Use clarify_request only for an initial greeting or general capability question with no stated "
        "support issue. Supported routes are standard_support and clarify_request."
    )


def triage_instructions() -> str:
    return (
        "You are the Triage Agent. Classify the customer message. Use billing_duplicate_charge only when "
        "the customer reports duplicate or repeated billing. Use stale_subscription_refund for subscription "
        "refund requests tied to old charges. Use consumed_product_return when the customer asks to return "
        "or refund a product they already consumed. Use recent_context to preserve the active issue across "
        "follow-up messages such as order numbers. Return only JSON with issue_type, urgency, sentiment, and "
        "optional missing_information."
    )


def investigation_agent_instructions() -> str:
    return (
        "You are the Investigation Agent. Decide which evidence the workflow must collect before policy "
        "and action planning. Return only JSON with required_evidence and reason. required_evidence must be "
        "a list using only these values: customer, charge, order, order_owner, subscription, account_access. "
        "Use customer for all actionable support requests. Use charge for duplicate-billing claims. Use order "
        "and order_owner when an order number is present or the active issue is a product return. Use "
        "subscription for subscription refund requests. Use account_access when the request mentions another "
        "account, spouse, wrong account, or different email."
    )


def policy_agent_instructions() -> str:
    return (
        "You are the Policy Agent. Choose the policy retrieval topic for the customer issue. "
        "Do not choose duplicate_charge_refund unless the triage issue is billing_duplicate_charge. "
        "Use consumed_product_return for consumed product return requests. "
        "Return only JSON with retrieval_query and reason."
    )


def action_agent_instructions() -> str:
    return (
        "You are the Action Agent. Choose the next support action based on customer, policy, "
        "and memory context. Return only JSON with action_type and reason."
    )


def validator_agent_instructions() -> str:
    return (
        "You are the Validator Agent. Check grounding, policy compliance, abuse-risk signals, and approval needs. "
        "Return only JSON with grounding_status, approval_required, evidence, and optional unsupported_claims."
    )


def escalation_agent_instructions() -> str:
    return (
        "You are the Escalation Agent. Prepare a concise human handoff when automated support should not finish "
        "the issue alone. Use only the provided validation, action, policy, and agent-state evidence. Return only "
        "JSON with escalation_type, reason, handoff_summary, next_owner, and evidence."
    )


def deterministic_decision_response(decision: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        output_text=json_for_prompt(decision),
        input_tokens=None,
        output_tokens=None,
        estimated_cost=None,
        raw_response={"decision_source": "deterministic"},
    )


def agent_decision_span_data(response: LLMResponse) -> dict[str, Any]:
    raw_response = response.raw_response or {}
    decision_source = str(raw_response.get("decision_source") or "deterministic")
    span_data = {
        "decision_source": decision_source,
        "prompt_version": PROMPT_VERSION,
    }
    model_metadata = model_call_span_data(raw_response.get("raw_response") if isinstance(raw_response.get("raw_response"), dict) else raw_response)
    span_data.update(model_metadata)
    fallback_reason = raw_response.get("fallback_reason")
    if fallback_reason:
        span_data["fallback_reason"] = fallback_reason
    validation_reason = raw_response.get("validation_reason")
    if validation_reason:
        span_data["validation_reason"] = validation_reason
    model_output_text = raw_response.get("model_output_text")
    if isinstance(model_output_text, str):
        span_data["model_output_text"] = model_output_text
    return span_data


def model_call_span_data(raw_response: dict[str, Any] | None) -> dict[str, Any]:
    if not raw_response:
        return {}
    span_data: dict[str, Any] = {}
    model = raw_response.get("agenttrace_model")
    if isinstance(model, str) and model:
        span_data["model"] = model
    attempts = raw_response.get("agenttrace_model_attempts")
    if isinstance(attempts, list):
        span_data["model_attempts"] = attempts
    fallback_used = raw_response.get("agenttrace_model_fallback_used")
    if isinstance(fallback_used, bool):
        span_data["model_fallback_used"] = fallback_used
    return span_data


def parse_agent_json(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def json_for_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)
