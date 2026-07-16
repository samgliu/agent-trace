"""Supervisor routing contract and conservative route validation."""

from __future__ import annotations

from typing import Any

STANDARD_SUPPORT_ROUTE = "standard_support"
CLARIFY_REQUEST_ROUTE = "clarify_request"
SUPPORTED_SUPERVISOR_ROUTES = {STANDARD_SUPPORT_ROUTE, CLARIFY_REQUEST_ROUTE}


def fallback_supervisor_decision(message: str, conversation_history: list[dict[str, Any]]) -> dict[str, str]:
    if _is_general_capability_question(message, conversation_history):
        return {
            "route": CLARIFY_REQUEST_ROUTE,
            "handoff_reason": "The customer has not stated an actionable support issue yet.",
        }
    return {
        "route": STANDARD_SUPPORT_ROUTE,
        "handoff_reason": "The customer request requires support investigation.",
    }


def validate_supervisor_decision(
    decision: dict[str, Any],
    *,
    message: str,
    conversation_history: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    fallback = fallback_supervisor_decision(message, conversation_history)
    requested_route = str(decision.get("route") or "")
    normalized_route = STANDARD_SUPPORT_ROUTE if requested_route == "triage" else requested_route

    if normalized_route not in SUPPORTED_SUPERVISOR_ROUTES:
        return fallback, {
            "decision_source": "policy_validation",
            "validation_reason": "unsupported_supervisor_route",
            "rejected_route": requested_route,
        }
    if normalized_route == CLARIFY_REQUEST_ROUTE and fallback["route"] == STANDARD_SUPPORT_ROUTE:
        return fallback, {
            "decision_source": "policy_validation",
            "validation_reason": "actionable_request_requires_support_route",
            "rejected_route": requested_route,
        }
    return {**decision, "route": normalized_route}, {}


def _is_general_capability_question(message: str, conversation_history: list[dict[str, Any]]) -> bool:
    if conversation_history:
        return False
    text = " ".join(message.lower().split())
    support_signals = (
        "account",
        "billing",
        "charge",
        "charged",
        "order",
        "refund",
        "return",
        "subscription",
        "cancel",
        "login",
        "access",
    )
    if any(signal in text for signal in support_signals):
        return False
    return text in {
        "hello",
        "hi",
        "hello, what can you help me with?",
        "what can you help me with?",
        "how can you help me?",
        "i need help",
    }
