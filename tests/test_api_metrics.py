import unittest
from pathlib import Path

from agenttrace.core.metrics import build_trace_metrics
from agenttrace.core.importer import load_trace_file


class ApiMetricsTest(unittest.TestCase):
    def test_build_trace_metrics(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

        metrics = build_trace_metrics(trace)

        self.assertEqual(metrics["trace_id"], trace.trace_id)
        self.assertEqual(metrics["span_count"], 10)
        self.assertEqual(metrics["spans_by_type"]["agent"], 4)
        self.assertEqual(metrics["spans_by_type"]["function_tool"], 2)
        self.assertEqual(metrics["input_tokens"], 1550)
        self.assertEqual(metrics["output_tokens"], 316)
        self.assertEqual(metrics["estimated_cost"], 0.0034)
        self.assertEqual(metrics["slowest_span"]["name"], "Supervisor Agent")

    def test_build_trace_metrics_counts_errors(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_tool_failure.json"))

        metrics = build_trace_metrics(trace)

        self.assertEqual(metrics["error_count"], 1)
        self.assertEqual(metrics["errored_span_count"], 1)
        self.assertEqual(metrics["spans_with_errors"][0]["span_id"], "span_failure_lookup_customer")
