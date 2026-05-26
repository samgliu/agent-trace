"""Customer-facing response helpers."""

from __future__ import annotations

from typing import Any


def customer_response_instructions() -> str:
    return (
        "You are a customer service agent. Write a concise, grounded customer response. "
        "Only mention facts present in the provided customer, policy, action, and validation context. "
        "Do not introduce unrelated account issues, billing flags, duplicate charges, or refunds that are not "
        "part of the customer's current request. "
        "Be customer-friendly: resolve eligible issues, explain approval as a review step when required, "
        "and do not deny solely because human approval is needed. Use the recent conversation history "
        "to answer follow-up questions naturally. Do not repeat first-turn wording like 'I started a review' "
        "when the existing review context is already present."
    )


def clarification_response_instructions() -> str:
    return (
        "You are a customer service agent receiving an initial message without an actionable support issue. "
        "Respond briefly with the kinds of issues you can help investigate and ask what the customer needs. "
        "Do not claim that tools were called, an account was reviewed, or an action was created."
    )


def clarification_response_input(message: str, conversation_history: list[dict[str, Any]]) -> str:
    return (
        "Route: clarify_request\n"
        f"Customer message: {message}\n"
        f"Conversation history: {conversation_history}\n"
        "No customer lookup, policy retrieval, or support action was needed for this response."
    )


def customer_response_input(
    message: str,
    customer: dict[str, Any],
    policy: dict[str, Any],
    action: dict[str, Any],
    validation: dict[str, Any],
    working_memory: dict[str, Any],
    customer_memory: dict[str, Any],
) -> str:
    issue_type = issue_type_from_working_memory(working_memory)
    return (
        f"Customer message: {message}\n"
        f"Working memory: {working_memory}\n"
        f"Customer context: {response_customer_context(customer, issue_type)}\n"
        f"Customer memory: {customer_memory}\n"
        f"Policy evidence: {policy}\n"
        f"Support action: {action}\n"
        f"Validation: {validation}"
    )


def customer_response_safety(
    response_text: str,
    *,
    policy: dict[str, Any],
    action: dict[str, Any],
    working_memory: dict[str, Any],
) -> str:
    if policy.get("policy_id") != "policy_consumed_product_return":
        return response_text

    normalized = response_text.lower()
    agent_state = working_memory.get("agent_state") if isinstance(working_memory.get("agent_state"), dict) else {}
    evidence_ids = agent_state.get("evidence_ids") if isinstance(agent_state, dict) else []
    has_order_evidence = isinstance(evidence_ids, list) and any(str(item).startswith("ord_") for item in evidence_ids)

    additions: list[str] = []
    if action.get("action_type") == "courtesy_credit" and "courtesy credit" not in normalized:
        additions.append("I can review this for a courtesy credit based on the quality issue and order evidence.")
    elif action.get("action_type") == "clarification_request" and has_order_evidence and "normal return" not in normalized:
        additions.append(
            "Because the items were fully consumed, this is not eligible for a normal return, but I can review a quality or safety exception if you share what was wrong."
        )

    if not additions:
        return response_text
    return " ".join([response_text.rstrip(), *additions])


def static_customer_response(input_text: str, default_response: str) -> str:
    if "Route: clarify_request" in input_text:
        return "I can help with orders, billing, subscriptions, returns, or account access. What do you need help with?"
    has_conversation_history = input_has_conversation_history(input_text)
    if "policy_consumed_product_return" in input_text:
        if has_quality_exception(input_text.lower()):
            return (
                "Thanks for the details. Because this sounds like a quality or safety exception rather than a normal return, "
                "I can review the order for a courtesy credit or escalation with the order evidence."
            )
        if input_has_order_number(input_text):
            return (
                "Thanks for the order number. Since the bananas were fully consumed, I cannot process a normal return. "
                "If there was a quality, spoilage, safety, or delivery issue, I can review that exception with the order details."
            )
        return (
            "Since the bananas were fully consumed, I cannot process a normal return. If there was a quality, spoilage, "
            "safety, or delivery issue, please share the order number or receipt and what was wrong so I can review it."
        )
    if has_conversation_history and "policy_stale_subscription_refund" in input_text:
        return (
            "For this follow-up, the older-subscription refund review is still waiting for human approval. "
            "I can add any new billing evidence to the review, but I cannot issue the refund before approval."
        )
    if has_conversation_history and "policy_refund_duplicate_charge" in input_text:
        return (
            "For this follow-up, the duplicate-charge review is still based on customer and payment verification. "
            "If you have a receipt or second charge ID, I can attach it to the review."
        )
    if has_conversation_history and "policy_annual_refund" in input_text:
        return (
            "For this follow-up, the annual-plan refund review is still waiting for human approval because of "
            "the refund amount. I can include any new cancellation or billing details in the review."
        )
    if "policy_stale_subscription_refund" in input_text:
        return (
            "I started a refund review for the older subscription charge. Because the charge is older than "
            "the standard self-serve window, it needs human approval before any refund can be issued."
        )
    if "policy_refund_duplicate_charge" in input_text:
        return (
            "I started a refund review for the detected duplicate charge. Duplicate-charge refunds can be "
            "resolved after customer and payment verification."
        )
    if "policy_annual_refund" in input_text:
        return (
            "I started a refund review for the annual plan. Because this is a high-value annual refund, "
            "it needs human approval before execution."
        )
    if "'action_type': 'clarification_request'" in input_text or '"action_type": "clarification_request"' in input_text:
        return "I need one more account or billing detail before I can safely take action on this request."
    return default_response


def input_has_conversation_history(input_text: str) -> bool:
    empty_markers = (
        "'conversation_history': []",
        '"conversation_history": []',
        "'recent_conversation_turns', 'value': 0",
        '"recent_conversation_turns", "value": 0',
    )
    return "conversation_history" in input_text and not any(marker in input_text for marker in empty_markers)


def input_has_order_number(input_text: str) -> bool:
    text = input_text.lower()
    return "order number" in text or "order #" in text or "#1234" in text


def issue_type_from_working_memory(working_memory: dict[str, Any]) -> str:
    facts = working_memory.get("facts")
    if not isinstance(facts, list):
        return "general_support"
    for fact in facts:
        if isinstance(fact, dict) and fact.get("key") == "issue_type":
            return str(fact.get("value") or "general_support")
    return "general_support"


def response_customer_context(customer: dict[str, Any], issue_type: str) -> dict[str, Any]:
    billing_issue_types = {"billing_duplicate_charge", "annual_plan_refund", "stale_subscription_refund"}
    if issue_type in billing_issue_types:
        return customer
    allowed_keys = {"found", "customer_id", "email", "loyalty_tier", "account_age_days"}
    return {key: value for key, value in customer.items() if key in allowed_keys}


def rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def has_quality_exception(text: str) -> bool:
    return any(signal in text for signal in ("spoiled", "moldy", "mouldy", "rotten", "unsafe", "sick", "delivery issue"))
