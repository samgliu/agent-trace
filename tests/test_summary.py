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
        trace = load_trace_file(Path("examples/support_triage/sample_trace_tool_failure.json"))

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

    def test_build_dashboard_summary_aggregates_memory_health(self) -> None:
        trace = Trace(
            trace_id="trace_memory",
            workflow_name="support-triage",
            status="passed",
            spans=[
                Span(
                    span_id="memory_write",
                    trace_id="trace_memory",
                    name="Write Working Memory",
                    span_type="memory_write",
                    span_data={"memory_store": "conversation_working_memory"},
                ),
                Span(
                    span_id="memory_read",
                    trace_id="trace_memory",
                    name="Read Customer Memory",
                    span_type="memory_read",
                    span_data={
                        "retrieved_memory_count": 1,
                        "memory_relevance_score": 0.42,
                        "memory_age_seconds": 86400 * 180,
                        "memory_used_in_response": False,
                    },
                ),
            ],
        )

        summary = build_dashboard_summary([build_trace_summary(trace)])

        self.assertEqual(summary["memory_read_count"], 1)
        self.assertEqual(summary["memory_write_count"], 1)
        self.assertEqual(summary["memory_retrieved_count"], 1)
        self.assertEqual(summary["memory_ignored_count"], 1)
        self.assertEqual(summary["memory_stale_count"], 1)
        self.assertEqual(summary["memory_warning_count"], 3)
        self.assertEqual(summary["memory_average_relevance"], 0.42)

    def test_build_dashboard_summary_aggregates_imported_memory_fixtures(self) -> None:
        healthy = build_trace_summary(load_trace_file(Path("examples/support_triage/sample_trace_memory_healthy.json")))
        warning = build_trace_summary(load_trace_file(Path("examples/support_triage/sample_trace_memory_warning.json")))

        summary = build_dashboard_summary([healthy, warning])

        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["memory_read_count"], 2)
        self.assertEqual(summary["memory_write_count"], 2)
        self.assertEqual(summary["memory_retrieved_count"], 3)
        self.assertEqual(summary["memory_ignored_count"], 1)
        self.assertEqual(summary["memory_stale_count"], 1)
        self.assertEqual(summary["memory_warning_count"], 3)
        self.assertEqual(summary["memory_average_relevance"], 0.665)


if __name__ == "__main__":
    unittest.main()
