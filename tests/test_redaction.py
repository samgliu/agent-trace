import unittest

from agenttrace.core.redaction import redact_value


class RedactionTest(unittest.TestCase):
    def test_redacts_common_sensitive_values_recursively(self) -> None:
        result = redact_value(
            {
                "email": "customer@example.com",
                "message": "Call me at 415-555-0199 and charge 4242 4242 4242 4242.",
                "nested": ["No sensitive data", "backup: billing@example.org"],
            }
        )

        self.assertEqual(result.value["email"], "[REDACTED_EMAIL]")
        self.assertEqual(result.value["message"], "Call me at [REDACTED_PHONE] and charge [REDACTED_PAYMENT].")
        self.assertEqual(result.value["nested"][1], "backup: [REDACTED_EMAIL]")
        self.assertTrue(result.contains_pii)
        self.assertEqual(result.types, ["email", "payment", "phone"])


if __name__ == "__main__":
    unittest.main()
