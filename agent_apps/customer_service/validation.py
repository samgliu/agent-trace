"""Validator, grounding, approval, and abuse-risk helpers."""

from __future__ import annotations

from typing import Any


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
    if policy.get("requires_approval"):
        if not enforced["approval_required"]:
            enforced["approval_required"] = True
            corrections.append("required_approval_enforced")
        if enforced["grounding_status"] != "recovered":
            enforced["grounding_status"] = "recovered"
            corrections.append("required_approval_grounding_recovered")

    abuse_risk_result = enforced.get("abuse_risk")
    if isinstance(abuse_risk_result, dict) and abuse_risk_result.get("requires_human_review"):
        if not enforced["approval_required"]:
            enforced["approval_required"] = True
            corrections.append("abuse_review_enforced")
        if enforced["grounding_status"] != "recovered":
            enforced["grounding_status"] = "recovered"
            corrections.append("abuse_review_grounding_recovered")
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
