import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local env may not have FastAPI installed yet.
    TestClient = None  # type: ignore[assignment]

from agenttrace.core.importer import load_trace_file
from agenttrace.storage.sqlite import SQLiteTraceStore


@unittest.skipIf(TestClient is None, "FastAPI is not installed")
class ApiEndpointsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.store = SQLiteTraceStore(Path(self.temp_dir.name) / "agenttrace.db")
        self.store.initialize()
        self.trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))
        self.store.save_trace(self.trace)
        from agenttrace.api.main import create_app

        self.client = TestClient(create_app(self.store))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_cors_allows_local_dashboard(self) -> None:
        response = self.client.options(
            "/traces",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_list_traces(self) -> None:
        response = self.client.get("/traces")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["limit"], 50)
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(payload["items"][0]["trace_id"], self.trace.trace_id)
        self.assertEqual(payload["items"][0]["span_count"], 10)
        self.assertEqual(payload["items"][0]["approval_pending_count"], 0)

    def test_list_traces_filters_by_pending_approval(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get("/traces?approval_status=pending")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], trace.trace_id)
        self.assertEqual(payload["items"][0]["approval_pending_count"], 1)
        self.assertEqual(payload["items"][0]["status"], "passed")
        self.assertEqual(payload["items"][0]["grounding_status"], "recovered")

    def test_list_traces_filters_by_workflow_status_and_date(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get(
            "/traces?workflow_name=support-triage&status=passed&started_after=2026-05-01T00:00:00Z"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)

    def test_list_traces_filters_by_source(self) -> None:
        trace = load_trace_file(
            Path("examples/openai_agents/sample_trace_export.json"),
            trace_format="openai-agents",
        )
        self.store.save_trace(trace)

        response = self.client.get("/traces?source_format=openai-agents&source_kind=trace_export")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], "oa_trace_support_triage_export")
        self.assertEqual(payload["items"][0]["source_format"], "openai-agents")
        self.assertEqual(payload["items"][0]["source_kind"], "trace_export")

    def test_list_workflows(self) -> None:
        response = self.client.get("/workflows")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["support-triage"])

    def test_dashboard_summary(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get("/dashboard/summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_runs"], 2)
        self.assertEqual(payload["approval_pending_count"], 1)
        self.assertEqual(payload["unsupported_claim_count"], 1)
        self.assertEqual(payload["workflow_counts"]["support-triage"], 2)
        self.assertEqual(payload["status_counts"]["passed"], 2)

    def test_get_trace(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trace_id"], self.trace.trace_id)
        self.assertEqual(len(payload["spans"]), 10)

    def test_ingest_trace_span_and_lifecycle(self) -> None:
        trace_payload = {
            "trace_id": "live_trace_api",
            "workflow_name": "support-triage",
            "status": "running",
            "started_at": "2026-05-03T21:00:00Z",
            "spans": [],
        }

        trace_response = self.client.post("/traces", json=trace_payload)
        span_response = self.client.post(
            "/traces/live_trace_api/spans",
            json={
                "span_id": "span_live_supervisor",
                "name": "Supervisor Agent",
                "span_type": "agent",
                "started_at": "2026-05-03T21:00:00Z",
                "ended_at": "2026-05-03T21:00:01Z",
                "input_tokens": 10,
                "output_tokens": 5,
                "estimated_cost": 0.0001,
            },
        )
        lifecycle_response = self.client.patch(
            "/traces/live_trace_api",
            json={"status": "passed", "ended_at": "2026-05-03T21:00:04Z"},
        )

        self.assertEqual(trace_response.status_code, 200)
        self.assertEqual(trace_response.json()["metadata"]["source_format"], "agenttrace")
        self.assertEqual(trace_response.json()["metadata"]["source_kind"], "live_api")
        self.assertIn("ingested_at", trace_response.json()["metadata"])
        self.assertEqual(span_response.status_code, 200)
        self.assertEqual(lifecycle_response.status_code, 200)
        self.assertEqual(lifecycle_response.json()["status"], "passed")
        summary = self.client.get("/traces?workflow_name=support-triage&status=passed").json()
        self.assertEqual(summary["total"], 2)

    def test_ingest_trace_validates_required_trace_id(self) -> None:
        response = self.client.post("/traces", json={"workflow_name": "support-triage"})

        self.assertEqual(response.status_code, 422)

    def test_ingest_openai_agents_trace(self) -> None:
        with Path("examples/openai_agents/sample_trace_export.json").open("r", encoding="utf-8") as file:
            import json

            payload = json.load(file)

        response = self.client.post("/ingest/openai-agents", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["trace_id"], "oa_trace_support_triage_export")
        self.assertEqual(len(body["spans"]), 5)
        self.assertEqual(body["metadata"]["source_format"], "openai-agents")
        self.assertEqual(body["metadata"]["source_kind"], "trace_export")
        self.assertIn("ingested_at", body["metadata"])

        raw_response = self.client.get("/traces/oa_trace_support_triage_export/raw")
        self.assertEqual(raw_response.status_code, 200)
        self.assertEqual(raw_response.json()["id"], "oa_trace_support_triage_export")
        self.assertEqual(raw_response.json()["spans"][1]["type"], "model_call")

    def test_get_spans(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}/spans")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 10)
        self.assertEqual(payload[0]["name"], "Supervisor Agent")

    def test_get_metrics(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}/metrics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_count"], 10)
        self.assertEqual(payload["input_tokens"], 1550)
        self.assertEqual(payload["estimated_cost"], 0.0034)

    def test_get_grounding(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get(f"/traces/{trace.trace_id}/grounding")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "recovered")
        self.assertEqual(payload["unsupported_claim_count"], 1)
        self.assertEqual(payload["unsupported_claims"][0]["span_name"], "Validator Agent")

    def test_missing_trace_returns_404(self) -> None:
        response = self.client.get("/traces/missing-trace")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Trace not found: missing-trace")

    def test_approve_approval_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/approve")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_data"]["approval_status"], "approved")
        self.assertEqual(payload["output"]["approval_status"], "approved")
        self.assertEqual(payload["span_data"]["approved_by"], "demo_user")
        self.assertIsNotNone(payload["span_data"]["approved_at"])

    def test_reject_approval_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/reject")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_data"]["approval_status"], "rejected")
        self.assertEqual(payload["output"]["approval_status"], "rejected")

    def test_revert_approval_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/approve")
        response = self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/revert")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_data"]["approval_status"], "blocked")
        self.assertEqual(payload["output"]["approval_status"], "blocked")
        self.assertIsNone(payload["span_data"]["approved_by"])
        self.assertIsNone(payload["span_data"]["approved_at"])

    def test_approval_action_rejects_non_approval_span(self) -> None:
        response = self.client.post(f"/traces/{self.trace.trace_id}/approvals/span_triage/approve")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Span is not an approval gate: span_triage")
