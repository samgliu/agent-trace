import unittest
from pathlib import Path

from agenttrace.core.importer import load_trace_file
from agenttrace.core.models import Span, Trace
from agenttrace.core.summary import build_dashboard_summary, build_trace_summary


class TraceSummaryTest(unittest.TestCase):
    def test_build_trace_summary_counts_approval_and_grounding(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

        summary = build_trace_summary(trace)

        self.assertEqual(summary["span_count"], 9)
        self.assertEqual(summary["approval_total_count"], 1)
        self.assertEqual(summary["approval_pending_count"], 1)
        self.assertEqual(summary["grounding_status"], "recovered")
        self.assertEqual(summary["unsupported_claim_count"], 1)

    def test_build_trace_summary_counts_span_errors(self) -> None:
        trace = Trace(
            trace_id="trace_with_error",
            workflow_name="support-triage",
            status="failed",
            spans=[
                Span(
                    span_id="span_tool_error",
                    trace_id="trace_with_error",
                    name="lookup_customer",
                    span_type="function_tool",
                    error={"message": "timeout"},
                )
            ],
        )

        summary = build_trace_summary(trace)

        self.assertEqual(summary["error_count"], 1)

    def test_build_dashboard_summary_aggregates_trace_summaries(self) -> None:
        happy_path = build_trace_summary(load_trace_file(Path("examples/support_triage/sample_trace.json")))
        intervention = build_trace_summary(load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json")))

        summary = build_dashboard_summary([happy_path, intervention])

        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["approval_pending_count"], 1)
        self.assertEqual(summary["unsupported_claim_count"], 1)
        self.assertEqual(summary["workflow_counts"], {"support-triage": 2})
        self.assertEqual(summary["status_counts"], {"passed": 2})
        self.assertEqual(summary["source_format_counts"], {"agenttrace": 2})
        self.assertEqual(summary["source_kind_counts"], {"trace_export": 2})
        self.assertEqual(summary["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
