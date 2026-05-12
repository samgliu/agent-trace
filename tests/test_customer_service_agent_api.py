import unittest

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local env may not have FastAPI installed yet.
    TestClient = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None, "FastAPI is not installed")
class CustomerServiceAgentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        from agent_apps.customer_service.api import create_app

        self.client = TestClient(create_app())

    def test_health_identifies_standalone_agent_service(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "customer-service-agent"})

    def test_run_support_triage_returns_trace_and_assistant_response(self) -> None:
        response = self.client.post(
            "/runs/support-triage",
            json={
                "trace_id": "trace_agent_service_run",
                "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
                "customer_email": "customer@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trace"]["trace_id"], "trace_agent_service_run")
        self.assertEqual(payload["trace"]["workflow_name"], "support-triage")
        self.assertEqual(payload["trace"]["status"], "passed")
        self.assertTrue(payload["assistant_response"])
        self.assertTrue(any(span["name"] == "create_refund_review" for span in payload["trace"]["spans"]))

    def test_run_support_triage_accepts_conversation_history(self) -> None:
        response = self.client.post(
            "/runs/support-triage",
            json={
                "trace_id": "trace_agent_service_followup",
                "message": "Order number: #1234",
                "customer_email": "customer@example.com",
                "conversation_history": [
                    {
                        "role": "user",
                        "content": "I'd like to return the banana I bought last week. I ate all of them already.",
                    },
                    {"role": "assistant", "content": "Please share the order number or receipt."},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        trace = response.json()["trace"]
        self.assertEqual(trace["metadata"]["conversation_history_count"], 2)
        self.assertTrue(any(span["name"] == "lookup_order" for span in trace["spans"]))


if __name__ == "__main__":
    unittest.main()
