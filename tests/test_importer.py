import unittest
from pathlib import Path

from agenttrace.core.importer import load_trace_file
from agenttrace.core.models import Trace


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
        approval_span = next(span for span in trace.spans if span.name == "Human Approval Gate")

        self.assertEqual(len(trace.spans), 9)
        self.assertEqual(validator_span.span_type, "guardrail")
        self.assertEqual(validator_span.output["grounded"], False)
        self.assertEqual(validator_span.output["unsupported_claims"][0]["claim"], "refund your last 3 months")
        self.assertEqual(approval_span.span_type, "approval")
        self.assertEqual(approval_span.span_data["approval_status"], "blocked")

    def test_trace_model_accepts_memory_span_types(self) -> None:
        trace = Trace.from_dict(
            {
                "trace_id": "trace_memory",
                "workflow_name": "support-triage",
                "status": "passed",
                "spans": [
                    {
                        "span_id": "span_memory_read",
                        "span_type": "memory_read",
                        "name": "Read Customer Memory",
                    },
                    {
                        "span_id": "span_memory_write",
                        "span_type": "memory_write",
                        "name": "Write Working Memory",
                    },
                ],
            }
        )

        self.assertEqual([span.span_type for span in trace.spans], ["memory_read", "memory_write"])
