"""Policy, triage, action, memory, and validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_apps.customer_service.domain import VALID_ACTIONS
from agent_apps.customer_service.support_tools import SupportToolsClient
from agent_apps.customer_service.validation import abuse_risk, approval_reason, enforce_validation, grounding_evidence


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
    if has_escalation_request(text):
        result["escalation_requested"] = True
    if quality_exception and issue_type == "consumed_product_return":
        result["quality_exception"] = True
    if issue_type == "general_support" and has_account_mismatch(current_text):
        result["missing_information"] = "verified account or matching order ownership"
    return result


def has_quality_exception(text: str) -> bool:
    return any(signal in text for signal in ("spoiled", "moldy", "mouldy", "rotten", "unsafe", "sick", "delivery issue"))


def has_account_mismatch(text: str) -> bool:
    return any(signal in text for signal in ("different email", "another email", "spouse", "not my account", "wrong account"))


def has_escalation_request(text: str) -> bool:
    return any(
        signal in text
        for signal in (
            "human agent",
            "real person",
            "representative",
            "speak to a human",
            "talk to a human",
            "talk to a person",
            "manager",
            "supervisor",
            "escalate",
        )
    )


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
        if triage_result.get("missing_information") and not expected.get("missing_information"):
            return validation_correction(
                "unsupported_missing_information",
                rejected_missing_information=triage_result.get("missing_information"),
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


ALLOWED_INVESTIGATION_EVIDENCE = {
    "account_access",
    "charge",
    "customer",
    "order",
    "order_owner",
    "subscription",
}


def investigation_plan(
    *,
    message: str,
    triage_result: dict[str, Any],
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue_type = str(triage_result.get("issue_type") or "general_support")
    order_number = extract_order_number(message)
    required_evidence = ["customer"]
    reasons = ["customer identity is the baseline evidence for actionable support"]

    if issue_type == "billing_duplicate_charge":
        required_evidence.append("charge")
        reasons.append("duplicate-billing claims need recent charge evidence")
    if issue_type in {"annual_plan_refund", "stale_subscription_refund"}:
        required_evidence.append("subscription")
        reasons.append("subscription refund requests need active subscription and last-charge evidence")
    if issue_type == "consumed_product_return":
        if order_number:
            required_evidence.extend(["order", "order_owner"])
            reasons.append("provided order numbers must be verified against the current customer")
        else:
            reasons.append("no order number is available yet, so order evidence cannot be collected")
    if has_account_mismatch(message.lower()):
        required_evidence.append("account_access")
        reasons.append("cross-account requests need account-access verification")

    return {
        "required_evidence": list(dict.fromkeys(required_evidence)),
        "reason": "; ".join(reasons),
    }


def validate_investigation_plan(
    plan: dict[str, Any],
    *,
    message: str,
    triage_result: dict[str, Any],
    conversation_history: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = investigation_plan(message=message, triage_result=triage_result, conversation_history=conversation_history)
    raw_evidence = plan.get("required_evidence")
    planned = [str(item) for item in raw_evidence] if isinstance(raw_evidence, list) else []
    unsupported = [item for item in planned if item not in ALLOWED_INVESTIGATION_EVIDENCE]
    missing = [item for item in expected["required_evidence"] if item not in planned]
    if unsupported or missing:
        return (
            {
                **plan,
                "required_evidence": expected["required_evidence"],
                "reason": expected["reason"],
            },
            validation_correction(
                "investigation_evidence_plan_corrected",
                rejected_required_evidence=planned,
                unsupported_evidence=unsupported,
                missing_evidence=missing,
            ),
        )
    return ({**plan, "required_evidence": list(dict.fromkeys(planned))}, {})


def action_type(triage_result: dict[str, Any], customer: dict[str, Any]) -> str:
    if not customer.get("found"):
        return "clarification_request"
    if triage_result.get("escalation_requested") and triage_result["issue_type"] in {"general_support", "account_access"}:
        return "escalation"
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


def action_plan(
    *,
    triage_result: dict[str, Any],
    customer: dict[str, Any],
    policy: dict[str, Any],
    customer_memory: dict[str, Any],
    agent_state_value: AgentState,
) -> dict[str, Any]:
    selected_action = action_type(triage_result, customer)
    policy_requires_approval = bool(policy.get("requires_approval"))
    risk_review_required = bool(agent_state_value.risk_signals)
    return {
        "action_type": selected_action,
        "reason": action_reason(triage_result, customer, policy, customer_memory),
        "customer_outcome": customer_outcome(selected_action, policy, agent_state_value),
        "requires_human_review": selected_action == "escalation" or policy_requires_approval or risk_review_required,
        "customer_message_goal": customer_message_goal(selected_action, policy, agent_state_value),
        "policy_boundary": policy_boundary(selected_action, policy, agent_state_value),
        "evidence_used": list(agent_state_value.evidence_ids),
    }


def customer_outcome(action_type_value: str, policy: dict[str, Any], agent_state_value: AgentState) -> str:
    if action_type_value == "refund_review" and policy.get("requires_approval"):
        return "approval_ready_refund_review"
    if action_type_value == "refund_review":
        return "refund_review_prepared"
    if action_type_value == "courtesy_credit":
        return "quality_exception_review_prepared"
    if action_type_value == "escalation":
        return "human_handoff_prepared"
    if action_type_value == "cancel_plan":
        return "plan_cancellation_prepared"
    if agent_state_value.missing_fields:
        return "missing_information_requested"
    return "support_action_prepared"


def customer_message_goal(action_type_value: str, policy: dict[str, Any], agent_state_value: AgentState) -> str:
    if action_type_value == "escalation":
        return "confirm human handoff and set follow-up expectation"
    if action_type_value == "refund_review" and policy.get("requires_approval"):
        return "explain review is prepared and approval is required before refund execution"
    if action_type_value == "refund_review":
        return "confirm refund review was prepared using verified evidence"
    if action_type_value == "courtesy_credit":
        return "explain quality exception review and courtesy-credit path"
    if agent_state_value.missing_fields:
        return "ask for the smallest missing detail needed to continue"
    return "explain the next support step clearly"


def policy_boundary(action_type_value: str, policy: dict[str, Any], agent_state_value: AgentState) -> str:
    policy_id = str(policy.get("policy_id") or "policy_unknown")
    if policy.get("requires_approval"):
        return f"{policy_id} requires human approval before customer-impacting execution."
    if action_type_value == "courtesy_credit":
        return f"{policy_id} allows exception review, not a normal consumed-product return."
    if agent_state_value.risk_signals:
        return f"{policy_id} requires human review for risk signals: {', '.join(agent_state_value.risk_signals)}."
    if action_type_value == "refund_review":
        return f"{policy_id} permits the selected action with collected evidence."
    if agent_state_value.missing_fields:
        return f"{policy_id} requires more information before irreversible action."
    return f"{policy_id} permits the selected action with collected evidence."


def validate_action_decision(
    action_decision: dict[str, Any],
    policy: dict[str, Any],
    expected_action: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    action_type_value = str(action_decision.get("action_type") or "")
    expected_action_type = str(expected_action["action_type"])
    validation = _validate_action_type(action_type_value, policy, expected_action_type)
    if validation:
        return expected_action, validation

    corrected = {**expected_action, **action_decision, "action_type": action_type_value.strip().lower()}
    invalid_fields = [
        field
        for field in ("customer_outcome", "customer_message_goal", "policy_boundary", "reason")
        if not isinstance(corrected.get(field), str) or not str(corrected.get(field)).strip()
    ]
    evidence_used = corrected.get("evidence_used")
    if not isinstance(evidence_used, list):
        invalid_fields.append("evidence_used")
        unsupported_evidence: list[str] = []
    else:
        allowed_evidence = {str(item) for item in expected_action.get("evidence_used", [])}
        unsupported_evidence = [str(item) for item in evidence_used if str(item) not in allowed_evidence]
        if unsupported_evidence:
            invalid_fields.append("evidence_used")
    if not isinstance(corrected.get("requires_human_review"), bool):
        invalid_fields.append("requires_human_review")
    for field in ("customer_outcome", "requires_human_review", "policy_boundary"):
        if field not in invalid_fields and corrected.get(field) != expected_action.get(field):
            invalid_fields.append(field)
    if invalid_fields:
        return (
            {**expected_action, "action_type": action_type_value.strip().lower()},
            validation_correction(
                "action_resolution_plan_corrected",
                invalid_action_fields=invalid_fields,
                unsupported_evidence_used=unsupported_evidence,
            ),
        )
    corrected["evidence_used"] = [str(item) for item in evidence_used]
    return corrected, {}


def _validate_action_type(action_type_value: str, policy: dict[str, Any], expected_action_type: str) -> dict[str, Any]:
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
    if expected_action_type == "escalation" and normalized_action != "escalation":
        return validation_correction(
            "escalation_required_by_customer_request",
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
    charge: dict[str, Any] | None = None,
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
    if charge:
        if charge.get("charge_id"):
            evidence_ids.append(str(charge["charge_id"]))
        charges = charge.get("charges")
        if isinstance(charges, list):
            evidence_ids.extend(str(item["charge_id"]) for item in charges if isinstance(item, dict) and item.get("charge_id"))
        if not charge.get("found"):
            missing_fields.extend(str(field) for field in charge.get("missing_fields", []))
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
    elif proposed_action == "escalation":
        next_required_step = "human_review"
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
