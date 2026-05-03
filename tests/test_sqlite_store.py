import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agenttrace.core.importer import load_trace_file
from agenttrace.storage.sqlite import SQLiteTraceStore


class SQLiteTraceStoreTest(unittest.TestCase):
    def test_save_and_get_trace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

            store.save_trace(trace)
            saved = store.get_trace(trace.trace_id)

            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.trace_id, trace.trace_id)
            self.assertEqual(saved.workflow_name, "support-triage")
            self.assertEqual(len(saved.spans), len(trace.spans))
            timeline = saved.format_timeline()
            self.assertGreaterEqual(timeline.count("Supervisor Agent"), 1)
            self.assertIn("Estimated cost: $0.0034", timeline)
            self.assertIn("Tokens: input=1550, output=316", timeline)
            self.assertIn("mcp:support-tools-mcp", timeline)
            self.assertNotIn("at 2026-05-01T23:00:00.000Z", timeline)

            verbose_timeline = saved.format_timeline(verbose=True)
            self.assertIn("at 2026-05-01T23:00:00.000Z", verbose_timeline)

    def test_list_traces(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

            store.save_trace(trace)
            traces = store.list_traces()

            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0].trace_id, trace.trace_id)

    def test_list_trace_summaries_filters_by_pending_approval(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            happy_path = load_trace_file(Path("examples/support_triage/sample_trace.json"))
            intervention = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

            store.save_trace(happy_path)
            store.save_trace(intervention)
            result = store.list_trace_summaries(approval_status="pending")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["trace_id"], intervention.trace_id)
            self.assertEqual(result["items"][0]["approval_pending_count"], 1)
            self.assertEqual(result["items"][0]["status"], "passed")
            self.assertEqual(result["items"][0]["grounding_status"], "recovered")

    def test_list_trace_summaries_filters_by_workflow_status_and_date(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            happy_path = load_trace_file(Path("examples/support_triage/sample_trace.json"))
            intervention = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

            store.save_trace(happy_path)
            store.save_trace(intervention)
            result = store.list_trace_summaries(
                workflow_name="support-triage",
                status="passed",
                started_after="2026-05-01T00:00:00Z",
            )

            self.assertEqual(result["total"], 2)

    def test_approval_update_refreshes_trace_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

            store.save_trace(trace)
            span = store.get_span(trace.trace_id, "span_approval_failure")
            assert span is not None
            span_data = dict(span.span_data)
            span_data["approval_status"] = "approved"
            store.update_span_payload(trace.trace_id, span.span_id, output={}, span_data=span_data)

            pending = store.list_trace_summaries(approval_status="pending")
            approved = store.list_trace_summaries(approval_status="approved")
            self.assertEqual(pending["total"], 0)
            self.assertEqual(approved["total"], 1)
