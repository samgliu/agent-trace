import unittest
from pathlib import Path

from agenttrace.core.importer import load_trace_file
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

    def test_build_dashboard_summary_aggregates_trace_summaries(self) -> None:
        happy_path = build_trace_summary(load_trace_file(Path("examples/support_triage/sample_trace.json")))
        intervention = build_trace_summary(load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json")))

        summary = build_dashboard_summary([happy_path, intervention])

        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["approval_pending_count"], 1)
        self.assertEqual(summary["unsupported_claim_count"], 1)
        self.assertEqual(summary["workflow_counts"], {"support-triage": 2})
        self.assertEqual(summary["status_counts"], {"passed": 1, "recovered": 1})


if __name__ == "__main__":
    unittest.main()
