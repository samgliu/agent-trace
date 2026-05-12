import unittest

from agenttrace.mcp_tools.tools import (
    create_quality_exception_review,
    create_refund_review,
    create_support_action,
    lookup_charge,
    lookup_customer,
    lookup_order,
    lookup_subscription,
    retrieve_policy,
    verify_order_owner,
)


class McpToolsTest(unittest.TestCase):
    def test_lookup_customer_returns_known_customer(self) -> None:
        result = lookup_customer("customer@example.com")

        self.assertTrue(result["found"])
        self.assertEqual(result["customer_id"], "cus_123")
        self.assertEqual(result["last_payment_status"], "duplicate_charge_detected")
        self.assertEqual(result["prior_refunds_12m"], 1)

    def test_lookup_customer_returns_missing_context_for_unknown_email(self) -> None:
        result = lookup_customer("unknown@example.com")

        self.assertFalse(result["found"])
        self.assertEqual(result["missing_fields"], ["verified_email"])

    def test_lookup_customer_can_timeout(self) -> None:
        with self.assertRaises(TimeoutError):
            lookup_customer("timeout@example.com")

    def test_retrieve_policy_returns_policy_evidence(self) -> None:
        result = retrieve_policy("annual_plan_refund")

        self.assertTrue(result["found"])
        self.assertEqual(result["policy_id"], "policy_annual_refund")
        self.assertTrue(result["requires_approval"])
        self.assertIn("refund_review", result["allowed_actions"])
        self.assertIn("customer_friendly_resolution", result)
        self.assertIn("abuse_controls", result)

    def test_retrieve_policy_returns_stale_subscription_refund_policy(self) -> None:
        result = retrieve_policy("stale_subscription_refund")

        self.assertTrue(result["found"])
        self.assertEqual(result["policy_id"], "policy_stale_subscription_refund")
        self.assertTrue(result["requires_approval"])
        self.assertIn("refund_review", result["allowed_actions"])

    def test_lookup_order_returns_order_evidence(self) -> None:
        result = lookup_order("#1234")

        self.assertTrue(result["found"])
        self.assertEqual(result["order_id"], "ord_1234")
        self.assertFalse(result["returnable"])
        self.assertTrue(result["quality_exception_eligible"])

    def test_lookup_charge_returns_customer_charge_evidence(self) -> None:
        result = lookup_charge("cus_123")

        self.assertTrue(result["found"])
        self.assertEqual(result["charges"][0]["charge_id"], "chg_dup_001")

    def test_lookup_subscription_returns_subscription_evidence(self) -> None:
        result = lookup_subscription("cus_annual_800")

        self.assertTrue(result["found"])
        self.assertEqual(result["subscription_id"], "sub_annual_800")
        self.assertEqual(result["plan"], "Annual Pro")
        self.assertEqual(result["billing_period"], "annual")

    def test_verify_order_owner_records_match_and_mismatch(self) -> None:
        matched = verify_order_owner("#1234", "cus_123")
        mismatched = verify_order_owner("#1234", "cus_other")

        self.assertTrue(matched["verified"])
        self.assertFalse(mismatched["verified"])
        self.assertEqual(mismatched["reason"], "order_customer_mismatch")

    def test_create_support_action_returns_action_record(self) -> None:
        result = create_support_action(
            customer_id="cus_123",
            action_type="refund_review",
            reason="Duplicate charge detected.",
        )

        self.assertEqual(result["action_id"], "act_cus_123_refund_review")
        self.assertEqual(result["status"], "created")

    def test_create_support_action_accepts_customer_friendly_resolution_actions(self) -> None:
        result = create_support_action(
            customer_id="cus_123",
            action_type="courtesy_credit",
            reason="Offer a policy-safe customer-friendly resolution.",
        )

        self.assertEqual(result["action_id"], "act_cus_123_courtesy_credit")
        self.assertEqual(result["status"], "created")

    def test_create_support_action_rejects_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            create_support_action(customer_id="cus_123", action_type="wire_money", reason="Not allowed.")

    def test_create_refund_review_returns_policy_linked_record(self) -> None:
        result = create_refund_review(
            customer_id="cus_123",
            policy_id="policy_refund_duplicate_charge",
            reason="Duplicate charge detected.",
            amount_usd=20,
            evidence_ids=["cus_123", "policy_refund_duplicate_charge"],
        )

        self.assertEqual(result["action_type"], "refund_review")
        self.assertEqual(result["amount_usd"], 20)
        self.assertEqual(result["evidence_ids"], ["cus_123", "policy_refund_duplicate_charge"])

    def test_create_quality_exception_review_returns_order_linked_record(self) -> None:
        result = create_quality_exception_review(
            customer_id="cus_123",
            order_id="ord_1234",
            reason="Moldy groceries reported.",
            evidence_ids=["cus_123", "ord_1234"],
        )

        self.assertEqual(result["action_type"], "courtesy_credit")
        self.assertEqual(result["order_id"], "ord_1234")
        self.assertEqual(result["status"], "created")


if __name__ == "__main__":
    unittest.main()
