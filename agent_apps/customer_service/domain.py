"""Customer-service domain fixtures and deterministic support operations."""

from __future__ import annotations

from typing import Any


CUSTOMERS: dict[str, dict[str, Any]] = {
    "customer@example.com": {
        "customer_id": "cus_123",
        "email": "customer@example.com",
        "plan": "Pro",
        "status": "active",
        "last_payment_status": "duplicate_charge_detected",
        "monthly_price_usd": 20,
        "duplicate_charge_amount_usd": 20,
        "loyalty_tier": "standard",
        "account_age_days": 640,
        "prior_refunds_12m": 1,
        "chargeback_count_12m": 0,
        "payment_method_verified": True,
    },
    "annual@example.com": {
        "customer_id": "cus_annual_800",
        "email": "annual@example.com",
        "plan": "Annual Pro",
        "status": "active",
        "last_payment_status": "paid",
        "annual_price_usd": 800,
        "loyalty_tier": "priority",
        "account_age_days": 980,
        "prior_refunds_12m": 0,
        "chargeback_count_12m": 0,
        "payment_method_verified": True,
    },
    "risk@example.com": {
        "customer_id": "cus_risk_777",
        "email": "risk@example.com",
        "plan": "Pro",
        "status": "active",
        "last_payment_status": "duplicate_charge_detected",
        "monthly_price_usd": 20,
        "duplicate_charge_amount_usd": 20,
        "loyalty_tier": "standard",
        "account_age_days": 12,
        "prior_refunds_12m": 6,
        "chargeback_count_12m": 2,
        "payment_method_verified": False,
    },
}


ORDERS: dict[str, dict[str, Any]] = {
    "1234": {
        "order_id": "ord_1234",
        "order_number": "1234",
        "customer_id": "cus_123",
        "email": "customer@example.com",
        "item": "bananas",
        "category": "grocery",
        "status": "delivered",
        "delivered_days_ago": 7,
        "amount_usd": 6,
        "returnable": False,
        "normal_return_blocked_reason": "fully_consumed",
        "quality_exception_eligible": True,
    },
    "A800": {
        "order_id": "ord_a800",
        "order_number": "A800",
        "customer_id": "cus_annual_800",
        "email": "annual@example.com",
        "item": "Annual Pro subscription",
        "category": "subscription",
        "status": "active",
        "amount_usd": 800,
        "returnable": False,
        "quality_exception_eligible": False,
    },
}


CHARGES: dict[str, dict[str, Any]] = {
    "chg_dup_001": {
        "charge_id": "chg_dup_001",
        "customer_id": "cus_123",
        "amount_usd": 20,
        "status": "duplicate_detected",
        "created_days_ago": 1,
        "payment_method_verified": True,
    },
    "chg_annual_800": {
        "charge_id": "chg_annual_800",
        "customer_id": "cus_annual_800",
        "amount_usd": 800,
        "status": "paid",
        "created_days_ago": 24,
        "payment_method_verified": True,
    },
}


SUBSCRIPTIONS: dict[str, dict[str, Any]] = {
    "sub_cus_123_pro": {
        "subscription_id": "sub_cus_123_pro",
        "customer_id": "cus_123",
        "plan": "Pro",
        "billing_period": "monthly",
        "status": "active",
        "last_charge_id": "chg_dup_001",
        "last_charge_amount_usd": 20,
        "last_charge_created_days_ago": 1,
        "refund_window_days": 180,
    },
    "sub_annual_800": {
        "subscription_id": "sub_annual_800",
        "customer_id": "cus_annual_800",
        "plan": "Annual Pro",
        "billing_period": "annual",
        "status": "active",
        "last_charge_id": "chg_annual_800",
        "last_charge_amount_usd": 800,
        "last_charge_created_days_ago": 24,
        "refund_window_days": 180,
    },
}


POLICIES: dict[str, dict[str, Any]] = {
    "duplicate_charge_refund": {
        "policy_id": "policy_refund_duplicate_charge",
        "topic": "duplicate_charge_refund",
        "version": "2026-05-01",
        "summary": (
            "Verified duplicate charges are eligible for immediate customer-friendly resolution after "
            "account and payment verification."
        ),
        "requires_approval": False,
        "allowed_actions": ["refund_review", "instant_refund", "courtesy_credit", "clarification_request"],
        "evidence_requirements": ["verified_customer_id", "duplicate_payment_signal", "policy_id"],
        "customer_friendly_resolution": (
            "Resolve verified duplicate charges without making the customer repeat known account context."
        ),
        "abuse_controls": {
            "max_low_risk_refunds_12m": 3,
            "require_review_when": ["high_prior_refund_count", "recent_chargebacks", "unverified_payment_method"],
            "principle": "Do not deny automatically; route risky but plausible refund requests to human review.",
        },
        "approval_threshold_usd": 100,
    },
    "annual_plan_refund": {
        "policy_id": "policy_annual_refund",
        "topic": "annual_plan_refund",
        "version": "2026-05-01",
        "summary": (
            "Annual plan refunds above $500 require human approval before execution, but the agent should "
            "prepare an approval-ready resolution and offer policy-safe alternatives."
        ),
        "requires_approval": True,
        "allowed_actions": ["refund_review", "courtesy_credit", "cancel_plan", "clarification_request"],
        "evidence_requirements": ["verified_customer_id", "annual_plan_amount", "policy_id"],
        "customer_friendly_resolution": (
            "Do not deny solely because approval is required; prepare the review and keep the customer informed."
        ),
        "abuse_controls": {
            "max_low_risk_refunds_12m": 2,
            "require_review_when": ["high_value_refund", "high_prior_refund_count", "recent_chargebacks"],
            "principle": "High-value refunds need human judgment before money movement.",
        },
        "approval_threshold_usd": 500,
    },
    "stale_subscription_refund": {
        "policy_id": "policy_stale_subscription_refund",
        "topic": "stale_subscription_refund",
        "version": "2026-05-01",
        "summary": (
            "Refund requests for subscription charges older than 180 days require human review. "
            "The agent may prepare a refund review, but must not claim a duplicate charge unless payment evidence shows one."
        ),
        "requires_approval": True,
        "allowed_actions": ["refund_review", "courtesy_credit", "clarification_request"],
        "evidence_requirements": ["verified_customer_id", "charge_age_or_billing_date", "policy_id"],
        "customer_friendly_resolution": (
            "Acknowledge the old charge, start the review when account context is verified, and clearly explain that approval is required."
        ),
        "abuse_controls": {
            "max_low_risk_refunds_12m": 2,
            "require_review_when": ["charge_older_than_threshold", "high_prior_refund_count", "recent_chargebacks"],
            "principle": "Old-charge refunds need review because evidence can be incomplete or stale.",
        },
        "approval_threshold_days": 180,
    },
    "general_support": {
        "policy_id": "policy_general_support",
        "topic": "general_support",
        "version": "2026-05-01",
        "summary": "General support requests should collect missing account or issue details before taking irreversible action.",
        "requires_approval": False,
        "allowed_actions": ["clarification_request", "escalation"],
        "evidence_requirements": ["verified_customer_id_or_contact", "customer_request"],
        "customer_friendly_resolution": "Ask for the smallest missing detail needed to route or resolve the request.",
    },
    "consumed_product_return": {
        "policy_id": "policy_consumed_product_return",
        "topic": "consumed_product_return",
        "version": "2026-05-01",
        "summary": (
            "Products that were fully consumed are not eligible for a normal return. The agent may review for "
            "a quality, spoilage, safety, or delivery exception after collecting order evidence and the issue reason."
        ),
        "requires_approval": False,
        "allowed_actions": ["clarification_request", "courtesy_credit", "escalation"],
        "evidence_requirements": ["order_number_or_receipt", "product_issue_reason", "consumption_status"],
        "customer_friendly_resolution": (
            "Set a clear boundary on normal returns for consumed items, then collect only the evidence needed "
            "to review a quality or safety exception."
        ),
    },
}


VALID_ACTIONS = {
    "refund_review",
    "instant_refund",
    "courtesy_credit",
    "escalation",
    "clarification_request",
    "cancel_plan",
}


def lookup_customer(email: str) -> dict[str, Any]:
    """Return customer account context for a support email."""
    normalized_email = email.strip().lower()
    if normalized_email == "timeout@example.com":
        raise TimeoutError("support-tools-mcp did not respond within 1500ms")
    customer = CUSTOMERS.get(normalized_email)
    if customer is None:
        return {
            "found": False,
            "email": normalized_email,
            "missing_fields": ["verified_email"],
        }
    return {"found": True, **customer}


def retrieve_policy(topic: str) -> dict[str, Any]:
    """Return support policy evidence by topic."""
    normalized_topic = topic.strip().lower()
    policy = POLICIES.get(normalized_topic)
    if policy is None:
        return {
            "found": False,
            "topic": normalized_topic,
            "fallback": "escalate_to_support_policy_review",
        }
    return {"found": True, **policy}


def lookup_order(order_number: str) -> dict[str, Any]:
    """Return order evidence by customer-provided order number."""
    normalized_order = order_number.strip().lstrip("#")
    order = ORDERS.get(normalized_order.upper()) or ORDERS.get(normalized_order)
    if order is None:
        return {
            "found": False,
            "order_number": normalized_order,
            "missing_fields": ["valid_order_number"],
        }
    return {"found": True, **order}


def lookup_charge(customer_id: str, charge_id: str | None = None) -> dict[str, Any]:
    """Return charge evidence for a customer."""
    normalized_charge_id = charge_id.strip() if charge_id else None
    if normalized_charge_id:
        charge = CHARGES.get(normalized_charge_id)
        if charge is None or charge.get("customer_id") != customer_id:
            return {
                "found": False,
                "customer_id": customer_id,
                "charge_id": normalized_charge_id,
                "missing_fields": ["matching_charge"],
            }
        return {"found": True, **charge}

    matches = [charge for charge in CHARGES.values() if charge.get("customer_id") == customer_id]
    if not matches:
        return {
            "found": False,
            "customer_id": customer_id,
            "missing_fields": ["charge_id_or_recent_charge"],
        }
    return {"found": True, "customer_id": customer_id, "charges": matches}


def lookup_subscription(customer_id: str) -> dict[str, Any]:
    """Return active subscription evidence for a customer."""
    matches = [subscription for subscription in SUBSCRIPTIONS.values() if subscription.get("customer_id") == customer_id]
    if not matches:
        return {
            "found": False,
            "customer_id": customer_id,
            "missing_fields": ["active_subscription"],
        }
    primary = matches[0]
    return {"found": True, **primary}


def verify_order_owner(order_number: str, customer_id: str) -> dict[str, Any]:
    """Verify that an order belongs to the current support customer."""
    order = lookup_order(order_number)
    if not order.get("found"):
        return {"verified": False, **order}
    verified = order.get("customer_id") == customer_id
    return {
        "verified": verified,
        "order_id": order.get("order_id"),
        "order_number": order.get("order_number"),
        "customer_id": customer_id,
        "order_customer_id": order.get("customer_id"),
        "reason": "order_customer_match" if verified else "order_customer_mismatch",
    }


def create_support_action(customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
    """Create a deterministic support action record."""
    normalized_action = action_type.strip().lower()
    if normalized_action not in VALID_ACTIONS:
        raise ValueError(f"Unsupported support action: {action_type}")
    action_id = f"act_{customer_id}_{normalized_action}"
    return {
        "action_id": action_id,
        "customer_id": customer_id,
        "action_type": normalized_action,
        "reason": reason,
        "status": "created",
    }


def create_refund_review(
    customer_id: str,
    policy_id: str,
    reason: str,
    amount_usd: int | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a refund review record with explicit policy and evidence links."""
    review_id = f"rr_{customer_id}_{policy_id}"
    return {
        "action_id": review_id,
        "review_id": review_id,
        "customer_id": customer_id,
        "policy_id": policy_id,
        "action_type": "refund_review",
        "reason": reason,
        "amount_usd": amount_usd,
        "evidence_ids": evidence_ids or [],
        "status": "created",
    }


def create_quality_exception_review(
    customer_id: str,
    order_id: str,
    reason: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a quality/safety exception review for consumed products."""
    review_id = f"qer_{customer_id}_{order_id}"
    return {
        "action_id": review_id,
        "review_id": review_id,
        "customer_id": customer_id,
        "order_id": order_id,
        "action_type": "courtesy_credit",
        "reason": reason,
        "evidence_ids": evidence_ids or [],
        "status": "created",
    }
