import unittest

from agenttrace.evals.support_triage import (
    SUPPORT_TRIAGE_EVAL_CASES,
    list_support_triage_eval_suites,
    run_support_triage_eval_suite,
)


class SupportTriageEvalsTest(unittest.TestCase):
    def test_lists_support_triage_eval_suite(self) -> None:
        suites = list_support_triage_eval_suites()

        self.assertEqual(suites[0]["suite_id"], "support-triage-core")
        self.assertEqual(suites[0]["case_count"], len(SUPPORT_TRIAGE_EVAL_CASES))
        self.assertEqual(suites[0]["cases"][0]["case_id"], "duplicate-charge-refund")

    def test_eval_suite_scores_core_support_triage_behaviors(self) -> None:
        result = run_support_triage_eval_suite()

        self.assertEqual(result.suite_id, "support-triage-core")
        self.assertEqual(result.total, 4)
        self.assertEqual(result.passed, 4)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.pass_rate, 1.0)
        by_case = {case_result.case.case_id: case_result for case_result in result.results}
        self.assertEqual(by_case["annual-refund-approval"].trace.status, "recovered")
        self.assertEqual(by_case["lookup-timeout-failure"].trace.status, "failed")

    def test_eval_result_payload_excludes_raw_trace_body(self) -> None:
        payload = run_support_triage_eval_suite().to_dict()

        self.assertEqual(payload["passed"], 4)
        self.assertEqual(payload["results"][0]["trace_id"], "trace_eval_support_triage_duplicate_charge_refund")
        self.assertNotIn("trace", payload["results"][0])
        self.assertTrue(all(check["passed"] for check in payload["results"][0]["checks"]))


if __name__ == "__main__":
    unittest.main()
