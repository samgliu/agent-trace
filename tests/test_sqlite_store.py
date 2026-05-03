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
