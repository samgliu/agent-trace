import unittest
from pathlib import Path

from agenttrace.core.grounding import build_grounding_summary
from agenttrace.core.importer import load_trace_file


class GroundingSummaryTest(unittest.TestCase):
    def test_happy_path_is_grounded(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

        summary = build_grounding_summary(trace)

        self.assertEqual(summary["status"], "grounded")
        self.assertEqual(summary["final_grounded"], True)
        self.assertEqual(summary["unsupported_claim_count"], 0)
        self.assertEqual(summary["supported_claim_count"], 2)

    def test_failure_trace_is_recovered_with_unsupported_claim(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

        summary = build_grounding_summary(trace)

        self.assertEqual(summary["status"], "recovered")
        self.assertEqual(summary["final_grounded"], True)
        self.assertEqual(summary["recovered"], True)
        self.assertEqual(summary["unsupported_claim_count"], 1)
        self.assertEqual(summary["unsupported_claims"][0]["claim"], "refund your last 3 months")
        self.assertEqual(summary["unsupported_claims"][0]["span_name"], "Validator Agent")
