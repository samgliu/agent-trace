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

    fallback_evidence = fallback.get("evidence")
    if not isinstance(fallback_evidence, list):
        fallback_evidence = []
    evidence = enforced.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    enforced["evidence"] = list(dict.fromkeys([*fallback_evidence, *evidence]))
    policy_missing_evidence = policy_evidence_gaps(policy, enforced["evidence"], action)
    missing_evidence = enforced.get("missing_evidence")
    if not isinstance(missing_evidence, list):
        missing_evidence = []
    if policy_missing_evidence:
        enforced["missing_evidence"] = list(dict.fromkeys([*missing_evidence, *policy_missing_evidence]))
    else:
        enforced["missing_evidence"] = missing_evidence

    corrections = []
    if policy_missing_evidence:
        corrections.append("policy_evidence_gap_detected")
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
    else:
        enforced.setdefault("validator_corrections", [])
    enforced["validation_report"] = validation_report(policy, action, enforced)
    return enforced


def validation_report(policy: dict[str, Any], action: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    allowed_actions = policy.get("allowed_actions")
    action_allowed = not isinstance(allowed_actions, list) or action.get("action_type") in allowed_actions
    action_created = action.get("status") == "created"
    unsupported_claims = validation.get("unsupported_claims")
    if not isinstance(unsupported_claims, list):
        unsupported_claims = []
    missing_evidence = validation.get("missing_evidence")
    if not isinstance(missing_evidence, list):
        missing_evidence = []

    policy_compliance_status = "passed" if action_created and action_allowed and not missing_evidence else "failed"
    approval_required = bool(validation.get("approval_required"))
    risk_review_required = bool(validation.get("risk_review_required"))
    grounding_status = str(validation.get("grounding_status") or "unknown")
    customer_safe_to_send = (
        grounding_status == "grounded"
        and not approval_required
        and not risk_review_required
        and action_created
        and action_allowed
        and not unsupported_claims
        and not missing_evidence
    )

    return {
        "grounding_status": grounding_status,
        "approval_required": approval_required,
        "policy_compliance": {
            "status": policy_compliance_status,
            "action_allowed": action_allowed,
            "action_created": action_created,
            "policy_id": policy.get("policy_id"),
            "action_type": action.get("action_type"),
        },
        "unsupported_claims": unsupported_claims,
        "missing_evidence": missing_evidence,
        "risk_review_required": risk_review_required,
        "customer_safe_to_send": customer_safe_to_send,
        "validator_corrections": validation.get("validator_corrections", []),
    }


def policy_evidence_gaps(policy: dict[str, Any], evidence: list[Any], action: dict[str, Any]) -> list[str]:
    requirements = policy.get("evidence_requirements")
    if not isinstance(requirements, list):
        return []
    evidence_ids = {str(item) for item in evidence if item}
    policy_id = str(policy.get("policy_id") or "")
    customer_id = str(action.get("customer_id") or "")

    checks = {
        "verified_customer_id": bool(customer_id) or any(item.startswith("cus_") for item in evidence_ids),
        "verified_customer_id_or_contact": bool(customer_id) or any(item.startswith("cus_") for item in evidence_ids),
        "policy_id": bool(policy_id and policy_id in evidence_ids),
        "duplicate_payment_signal": any(item.startswith("chg_") for item in evidence_ids),
        "annual_plan_amount": any(item.startswith("sub_") for item in evidence_ids),
        "charge_age_or_billing_date": any(item.startswith(("sub_", "chg_")) for item in evidence_ids),
        "order_number_or_receipt": any(item.startswith("ord_") for item in evidence_ids),
    }
    return [str(requirement) for requirement in requirements if requirement in checks and not checks[requirement]]


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
