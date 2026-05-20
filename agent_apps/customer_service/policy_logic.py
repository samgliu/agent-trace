"""Policy, triage, action, memory, and validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_apps.customer_service.domain import VALID_ACTIONS
from agent_apps.customer_service.support_tools import SupportToolsClient


@dataclass(frozen=True)
class AgentState:
    active_issue: str
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    risk_signals: tuple[str, ...] = ()
    proposed_action: str | None = None
    next_required_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_issue": self.active_issue,
            "missing_fields": list(self.missing_fields),
            "evidence_ids": list(self.evidence_ids),
            "risk_signals": list(self.risk_signals),
            "proposed_action": self.proposed_action,
            "next_required_step": self.next_required_step,
        }


def conversation_context(message: str, conversation_history: list[dict[str, Any]] | None = None) -> str:
    recent_turns = conversation_history[-4:] if conversation_history else []
    parts = [str(turn.get("content") or "") for turn in recent_turns]
    parts.append(message)
    return "\n".join(part for part in parts if part).lower()


def triage(message: str, conversation_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current_text = message.lower()
    text = conversation_context(message, conversation_history)
    quality_exception = has_quality_exception(text)
    if has_account_mismatch(current_text):
        issue_type = "general_support"
        urgency = "medium"
    elif "charged twice" in current_text or "duplicate" in current_text:
        issue_type = "billing_duplicate_charge"
        urgency = "medium"
    elif ("return" in text or "refund" in text) and (
        "banana" in text or "bananas" in text or "grocery" in text or "product" in text or "item" in text
    ) and ("ate" in text or "eaten" in text or "consumed" in text or "used all" in text):
        issue_type = "consumed_product_return"
        urgency = "low"
    elif "charged twice" in text or "duplicate" in text:
        issue_type = "billing_duplicate_charge"
        urgency = "medium"
    elif ("refund" in text and "subscription" in text) and (
        "year ago" in text or "years ago" in text or "3 years" in text or "old charge" in text
    ):
        issue_type = "stale_subscription_refund"
        urgency = "medium"
    elif "annual" in text and "refund" in text:
        issue_type = "annual_plan_refund"
        urgency = "medium"
    elif "access" in text or "login" in text:
        issue_type = "account_access"
        urgency = "high"
    else:
        issue_type = "general_support"
        urgency = "low"
    result = {"issue_type": issue_type, "urgency": urgency, "sentiment": "concerned"}
    if quality_exception and issue_type == "consumed_product_return":
        result["quality_exception"] = True
    if issue_type == "general_support" and has_account_mismatch(current_text):
        result["missing_information"] = "verified account or matching order ownership"
    return result


def has_quality_exception(text: str) -> bool:
    return any(signal in text for signal in ("spoiled", "moldy", "mouldy", "rotten", "unsafe", "sick", "delivery issue"))


def has_account_mismatch(text: str) -> bool:
    return any(signal in text for signal in ("different email", "another email", "spouse", "not my account", "wrong account"))


def validation_correction(reason: str, **metadata: Any) -> dict[str, Any]:
    return {
        "decision_source": "policy_validation",
        "validation_reason": reason,
        **metadata,
    }


def validate_triage_decision(
    message: str,
    triage_result: dict[str, Any],
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected = triage(message, conversation_history)
    known_issue_types = {
        "account_access",
        "annual_plan_refund",
        "billing_duplicate_charge",
        "consumed_product_return",
        "general_support",
        "stale_subscription_refund",
    }
    if triage_result.get("issue_type") not in known_issue_types:
        return validation_correction("unsupported_issue_type", rejected_issue_type=triage_result.get("issue_type"))
    if triage_result.get("issue_type") == expected["issue_type"]:
        if expected.get("quality_exception") and not triage_result.get("quality_exception"):
            return validation_correction(
                "missing_quality_exception_signal",
                rejected_issue_type=triage_result.get("issue_type"),
            )
        return {}
    if expected["issue_type"] in {
        "account_access",
        "stale_subscription_refund",
        "billing_duplicate_charge",
        "annual_plan_refund",
        "consumed_product_return",
        "general_support",
    }:
        return validation_correction(
            "message_policy_signal_mismatch",
            rejected_issue_type=triage_result.get("issue_type"),
        )
    return {}


def policy_topic(triage_result: dict[str, Any], customer: dict[str, Any]) -> str:
    if triage_result["issue_type"] == "consumed_product_return":
        return "consumed_product_return"
    if triage_result["issue_type"] == "annual_plan_refund" or customer.get("annual_price_usd", 0) > 500:
        return "annual_plan_refund"
    if triage_result["issue_type"] == "stale_subscription_refund":
        return "stale_subscription_refund"
    if triage_result["issue_type"] == "billing_duplicate_charge":
        return "duplicate_charge_refund"
    return "general_support"


def validate_policy_decision(policy_topic_value: str, expected_policy_topic: str) -> dict[str, Any]:
    if policy_topic_value == expected_policy_topic:
        return {}
    return validation_correction("policy_topic_mismatch", rejected_policy_topic=policy_topic_value)


def action_type(triage_result: dict[str, Any], customer: dict[str, Any]) -> str:
    if not customer.get("found"):
        return "clarification_request"
    if triage_result["issue_type"] == "account_access":
        return "escalation"
    if triage_result["issue_type"] == "consumed_product_return" and triage_result.get("quality_exception"):
        return "courtesy_credit"
    if triage_result["issue_type"] in {"general_support", "consumed_product_return"}:
        return "clarification_request"
    return "refund_review"


def action_reason(
    triage_result: dict[str, Any],
    customer: dict[str, Any],
    policy: dict[str, Any],
    customer_memory: dict[str, Any],
) -> str:
    memory_note = ""
    if customer_memory.get("used_in_response"):
        memory_note = f" Memory context: {customer_memory['memories'][0]['summary']}"
    return (
        f"{triage_result['issue_type']} for {customer.get('customer_id', 'unknown customer')} "
        f"under {policy.get('policy_id', 'missing policy')}.{memory_note}"
    )


def validate_action_decision(action_type_value: str, policy: dict[str, Any], expected_action_type: str) -> dict[str, Any]:
    normalized_action = action_type_value.strip().lower()
    if normalized_action not in VALID_ACTIONS:
        return validation_correction("unsupported_action_type", rejected_action_type=action_type_value)
    allowed_actions = policy.get("allowed_actions")
    if isinstance(allowed_actions, list) and normalized_action not in allowed_actions:
        return validation_correction(
            "action_not_allowed_by_policy",
            rejected_action_type=action_type_value,
            policy_allowed_actions=allowed_actions,
        )
    policy_id = str(policy.get("policy_id") or "")
    if (
        expected_action_type == "clarification_request"
        and policy_id == "policy_general_support"
        and normalized_action != "clarification_request"
    ):
        return validation_correction(
            "clarification_required_by_policy_path",
            rejected_action_type=action_type_value,
            policy_id=policy_id,
        )
    if (
        expected_action_type == "courtesy_credit"
        and policy_id == "policy_consumed_product_return"
        and normalized_action != "courtesy_credit"
    ):
        return validation_correction(
            "quality_exception_action_required",
            rejected_action_type=action_type_value,
            policy_id=policy_id,
        )
    if (
        expected_action_type == "refund_review"
        and policy_id
        in {
            "policy_refund_duplicate_charge",
            "policy_annual_refund",
            "policy_stale_subscription_refund",
        }
        and normalized_action != "refund_review"
    ):
        return validation_correction(
            "refund_review_required_by_policy_path",
            rejected_action_type=action_type_value,
            policy_id=policy_id,
        )
    return {}


def create_domain_action(
    tools_client: SupportToolsClient,
    *,
    customer: dict[str, Any],
    policy: dict[str, Any],
    action_type: str,
    action_reason: str,
    order: dict[str, Any] | None,
    agent_state: AgentState,
) -> tuple[dict[str, Any], str]:
    customer_id = str(customer.get("customer_id") or "unknown")
    evidence_ids = list(agent_state.evidence_ids)
    if action_type == "refund_review":
        amount = refund_amount(customer, order)
        return (
            tools_client.create_refund_review(
                customer_id,
                str(policy.get("policy_id") or "policy_unknown"),
                action_reason,
                amount,
                evidence_ids,
            ),
            "create_refund_review_tool",
        )
    if action_type == "courtesy_credit" and order and order.get("order_id"):
        return (
            tools_client.create_quality_exception_review(
                customer_id,
                str(order["order_id"]),
                action_reason,
                evidence_ids,
            ),
            "create_quality_exception_review_tool",
        )
    return (
        tools_client.create_support_action(customer_id, action_type, action_reason),
        "create_support_action_tool",
    )


def refund_amount(customer: dict[str, Any], order: dict[str, Any] | None) -> int | None:
    if order and isinstance(order.get("amount_usd"), int):
        return int(order["amount_usd"])
    for key in ("duplicate_charge_amount_usd", "annual_price_usd", "monthly_price_usd"):
        if isinstance(customer.get(key), int):
            return int(customer[key])
    return None


def extract_order_number(message: str) -> str | None:
    match = re.search(r"(?:order(?:\s+number)?[:\s#]*|#)([A-Za-z0-9-]{3,20})", message, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def agent_state(
    *,
    triage: dict[str, Any],
    customer: dict[str, Any] | None = None,
    order: dict[str, Any] | None = None,
    order_owner: dict[str, Any] | None = None,
    account_access: dict[str, Any] | None = None,
    subscription: dict[str, Any] | None = None,
    proposed_action: str | None = None,
    policy: dict[str, Any] | None = None,
) -> AgentState:
    missing_fields: list[str] = []
    evidence_ids: list[str] = []
    risk_signals: list[str] = []
    issue_type = str(triage.get("issue_type") or "general_support")

    if triage.get("missing_information"):
        missing_fields.append(str(triage["missing_information"]))
    if customer:
        if customer.get("customer_id"):
            evidence_ids.append(str(customer["customer_id"]))
        if not customer.get("found", True):
            missing_fields.extend(str(field) for field in customer.get("missing_fields", []))
        prior_refunds = int(customer.get("prior_refunds_12m") or 0)
        chargebacks = int(customer.get("chargeback_count_12m") or 0)
        account_age_days = int(customer.get("account_age_days") or 0)
        if prior_refunds > 3:
            risk_signals.append("high_prior_refund_count")
        if chargebacks > 0:
            risk_signals.append("recent_chargebacks")
        if customer.get("found") and not customer.get("payment_method_verified", True):
            risk_signals.append("unverified_payment_method")
        if account_age_days and account_age_days < 30:
            risk_signals.append("new_account")
    if policy and policy.get("policy_id"):
        evidence_ids.append(str(policy["policy_id"]))
    if order:
        if order.get("order_id"):
            evidence_ids.append(str(order["order_id"]))
        if not order.get("found"):
            missing_fields.extend(str(field) for field in order.get("missing_fields", []))
    if order_owner:
        if order_owner.get("verified"):
            evidence_ids.append(str(order_owner.get("reason") or "order_customer_match"))
        else:
            risk_signals.append("order_customer_mismatch")
    if account_access:
        evidence_id = account_access.get("evidence_id")
        if evidence_id:
            evidence_ids.append(str(evidence_id))
        if not account_access.get("verified"):
            risk_signals.append(str(account_access.get("reason") or "account_access_mismatch"))
            missing_fields.extend(str(field) for field in account_access.get("missing_fields", []))
    if subscription:
        if subscription.get("subscription_id"):
            evidence_ids.append(str(subscription["subscription_id"]))
        if not subscription.get("found"):
            missing_fields.extend(str(field) for field in subscription.get("missing_fields", []))

    if issue_type == "consumed_product_return" and not order:
        missing_fields.append("order_number_or_receipt")
        if not triage.get("quality_exception"):
            missing_fields.append("product_issue_reason")

    next_required_step = "create_support_action"
    if missing_fields and proposed_action == "clarification_request":
        next_required_step = "collect_missing_information"
    elif policy and policy.get("requires_approval"):
        next_required_step = "human_approval"
    elif risk_signals:
        next_required_step = "human_review"

    return AgentState(
        active_issue=issue_type,
        missing_fields=tuple(dict.fromkeys(missing_fields)),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        risk_signals=tuple(dict.fromkeys(risk_signals)),
        proposed_action=proposed_action,
        next_required_step=next_required_step,
    )


def enforce_validation(
    policy: dict[str, Any],
    action: dict[str, Any],
    validation: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    enforced = {**fallback, **validation}
    enforced["approval_required"] = bool(enforced.get("approval_required"))
    enforced["grounding_status"] = str(enforced.get("grounding_status") or fallback["grounding_status"])

    evidence = enforced.get("evidence")
    if not isinstance(evidence, list):
        enforced["evidence"] = fallback["evidence"]

    corrections = []
    if policy.get("requires_approval") and not enforced["approval_required"]:
        enforced["approval_required"] = True
        enforced["grounding_status"] = "recovered"
        corrections.append("required_approval_enforced")

    abuse_risk_result = enforced.get("abuse_risk")
    if isinstance(abuse_risk_result, dict) and abuse_risk_result.get("requires_human_review") and not enforced["approval_required"]:
        enforced["approval_required"] = True
        enforced["grounding_status"] = "recovered"
        corrections.append("abuse_review_enforced")
    enforced["risk_review_required"] = bool(isinstance(abuse_risk_result, dict) and abuse_risk_result.get("requires_human_review"))

    if (
        not policy.get("requires_approval")
        and not enforced["risk_review_required"]
        and action.get("action_type") == "clarification_request"
        and enforced["approval_required"]
    ):
        enforced["approval_required"] = False
        enforced["grounding_status"] = fallback["grounding_status"]
        corrections.append("unnecessary_approval_removed")

    if action.get("status") != "created":
        enforced["grounding_status"] = "failed"
        corrections.append("action_not_created")

    allowed_actions = policy.get("allowed_actions")
    if isinstance(allowed_actions, list) and action.get("action_type") not in allowed_actions:
        enforced["grounding_status"] = "failed"
        corrections.append("action_not_allowed_by_policy")

    enforced.setdefault("grounding_evidence", grounding_evidence({}, policy, action))
    enforced.setdefault("allowed_actions", policy.get("allowed_actions", []))
    enforced.setdefault("customer_friendly_resolution", policy.get("customer_friendly_resolution"))

    if corrections:
        enforced["validator_corrections"] = corrections
    return enforced


def abuse_risk(customer: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    signals: list[str] = []
    prior_refunds = int(customer.get("prior_refunds_12m") or 0)
    chargebacks = int(customer.get("chargeback_count_12m") or 0)
    account_age_days = int(customer.get("account_age_days") or 0)
    payment_verified = bool(customer.get("payment_method_verified", False))
    controls = policy.get("abuse_controls") if isinstance(policy.get("abuse_controls"), dict) else {}
    max_refunds = int(controls.get("max_low_risk_refunds_12m") or 3)

    if prior_refunds > max_refunds:
        signals.append("high_prior_refund_count")
    if chargebacks > 0:
        signals.append("recent_chargebacks")
    if account_age_days and account_age_days < 30:
        signals.append("new_account")
    if customer.get("found") and not payment_verified:
        signals.append("unverified_payment_method")

    level = "low"
    if len(signals) >= 2 or "recent_chargebacks" in signals:
        level = "high"
    elif signals:
        level = "medium"

    return {
        "level": level,
        "signals": signals,
        "requires_human_review": level == "high",
        "principle": controls.get("principle"),
    }


def approval_reason(validation: dict[str, Any]) -> str:
    if validation.get("risk_review_required"):
        return "Human review required by abuse-risk controls."
    return "Policy requires human approval."


def grounding_evidence(customer: dict[str, Any], policy: dict[str, Any], action: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    customer_id = customer.get("customer_id") or action.get("customer_id")
    if customer_id:
        evidence.append({"type": "customer", "id": customer_id})
    policy_id = policy.get("policy_id")
    if policy_id:
        evidence.append({"type": "policy", "id": policy_id})
    action_id = action.get("action_id")
    if action_id:
        evidence.append({"type": "action", "id": action_id})
    return evidence


def mcp_span_data(tool_name: str) -> dict[str, Any]:
    return {"tool_protocol": "mcp", "tool_server": "mcp-tools", "tool_name": tool_name}


def working_memory(
    message: str,
    customer_email: str,
    triage_result: dict[str, Any],
    conversation_history: list[dict[str, Any]] | None = None,
    agent_state_value: AgentState | None = None,
) -> dict[str, Any]:
    conversation_history = conversation_history or []
    return {
        "memory_key": f"working:{customer_email}",
        "facts": [
            {"key": "latest_customer_message", "value": message},
            {"key": "issue_type", "value": triage_result["issue_type"]},
            {"key": "urgency", "value": triage_result["urgency"]},
            {"key": "recent_conversation_turns", "value": len(conversation_history)},
        ],
        "conversation_history": conversation_history,
        "agent_state": (agent_state_value or agent_state(triage=triage_result)).to_dict(),
    }


def customer_memory(customer: dict[str, Any], issue_type: str = "general_support") -> dict[str, Any]:
    customer_id = str(customer.get("customer_id") or "unknown")
    if not customer.get("found"):
        memory = {
            "memory_id": "mem_unknown_legacy_note",
            "summary": "Legacy unverified note says the customer may prefer phone support.",
            "source": "support_history",
        }
        return {
            "memories": [memory],
            "relevance_score": 0.42,
            "memory_age_seconds": 86400 * 180,
            "used_in_response": False,
        }
    if issue_type == "consumed_product_return":
        memory = {
            "memory_id": f"mem_{customer_id}_preference",
            "summary": "Customer prefers concise email updates.",
            "source": "support_history",
        }
        return {
            "memories": [memory],
            "relevance_score": 0.72,
            "memory_age_seconds": 86400 * 30,
            "used_in_response": True,
        }
    if customer.get("annual_price_usd", 0) > 500:
        memory = {
            "memory_id": f"mem_{customer_id}_annual_refund",
            "summary": "Prior refund requests on annual plans require careful approval review.",
            "source": "support_history",
        }
        return {
            "memories": [memory],
            "relevance_score": 0.91,
            "memory_age_seconds": 86400 * 12,
            "used_in_response": True,
        }
    memory = {
        "memory_id": f"mem_{customer_id}_billing",
        "summary": "Customer previously contacted support about billing and prefers concise email updates.",
        "source": "support_history",
    }
    return {
        "memories": [memory],
        "relevance_score": 0.82,
        "memory_age_seconds": 86400 * 4,
        "used_in_response": True,
    }
