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
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["trace_id"], self.trace.trace_id)
        self.assertEqual(payload[0]["spans"], [])

    def test_get_trace(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trace_id"], self.trace.trace_id)
        self.assertEqual(len(payload["spans"]), 10)

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

    def test_missing_trace_returns_404(self) -> None:
        response = self.client.get("/traces/missing-trace")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Trace not found: missing-trace")
