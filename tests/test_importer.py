import unittest
from pathlib import Path

from agenttrace.core.importer import load_trace_file


class ImporterTest(unittest.TestCase):
    def test_load_sample_trace(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

        self.assertEqual(trace.trace_id, "trace_support_triage_happy_path")
        self.assertEqual(trace.workflow_name, "support-triage")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(len(trace.spans), 10)
        self.assertEqual(trace.duration_ms, 4000)

    def test_sample_trace_contains_mcp_tool_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

        lookup_span = next(span for span in trace.spans if span.name == "lookup_customer")

        self.assertEqual(lookup_span.span_type, "function_tool")
        self.assertEqual(lookup_span.span_data["tool_protocol"], "mcp")
        self.assertEqual(lookup_span.span_data["tool_server"], "support-tools-mcp")

    def test_load_grounding_failure_trace(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

        validator_span = next(span for span in trace.spans if span.name == "Validator Agent")

        self.assertEqual(trace.status, "recovered")
        self.assertEqual(len(trace.spans), 8)
        self.assertEqual(validator_span.span_type, "guardrail")
        self.assertEqual(validator_span.output["grounded"], False)
        self.assertEqual(validator_span.output["unsupported_claims"][0]["claim"], "refund your last 3 months")
