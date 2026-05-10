import unittest

from agenttrace.mcp_tools.tools import create_support_action, lookup_customer, retrieve_policy


class McpToolsTest(unittest.TestCase):
    def test_lookup_customer_returns_known_customer(self) -> None:
        result = lookup_customer("customer@example.com")

        self.assertTrue(result["found"])
        self.assertEqual(result["customer_id"], "cus_123")
        self.assertEqual(result["last_payment_status"], "duplicate_charge_detected")

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


if __name__ == "__main__":
    unittest.main()
