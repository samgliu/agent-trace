import unittest

from agenttrace.evals.support_triage import (
    EvalCase,
    EvalCaseResult,
    EvalCheck,
    EvalSuiteResult,
    SUPPORT_TRIAGE_EVAL_CASES,
    build_eval_report,
    format_eval_report,
    list_support_triage_eval_suites,
    run_support_triage_eval_suite,
)
from agenttrace.core.models import Trace


class SupportTriageEvalsTest(unittest.TestCase):
    def test_lists_support_triage_eval_suite(self) -> None:
        suites = list_support_triage_eval_suites()

        self.assertEqual(suites[0]["suite_id"], "support-triage-core")
        self.assertEqual(suites[0]["case_count"], len(SUPPORT_TRIAGE_EVAL_CASES))
        self.assertEqual(suites[0]["cases"][0]["case_id"], "duplicate-charge-refund")

    def test_eval_suite_scores_core_support_triage_behaviors(self) -> None:
        result = run_support_triage_eval_suite()

        self.assertEqual(result.suite_id, "support-triage-core")
        self.assertEqual(result.total, 11)
        self.assertEqual(result.passed, 11)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.pass_rate, 1.0)
        by_case = {case_result.case.case_id: case_result for case_result in result.results}
        self.assertEqual(by_case["annual-refund-approval"].trace.status, "recovered")
        self.assertEqual(by_case["stale-subscription-refund-approval"].trace.status, "recovered")
        self.assertEqual(by_case["lookup-timeout-failure"].trace.status, "failed")
        self.assertTrue(by_case["consumed-product-return-follow-up"].passed)
        self.assertTrue(by_case["explicit-topic-switch-to-duplicate-charge"].passed)
        self.assertTrue(by_case["consumed-product-quality-exception"].passed)
        self.assertTrue(by_case["repeated-refund-abuse-review"].passed)
        self.assertTrue(by_case["account-mismatch-clarification"].passed)
        self.assertEqual(by_case["consumed-product-return-follow-up"].case.conversation_history[0]["role"], "user")

    def test_eval_result_payload_excludes_raw_trace_body(self) -> None:
        payload = run_support_triage_eval_suite().to_dict()

        self.assertEqual(payload["passed"], 11)
        self.assertEqual(payload["results"][0]["trace_id"], "trace_eval_support_triage_duplicate_charge_refund")
        self.assertNotIn("trace", payload["results"][0])
        self.assertTrue(all(check["passed"] for check in payload["results"][0]["checks"]))

    def test_eval_cases_include_multi_turn_quality_checks(self) -> None:
        result = run_support_triage_eval_suite()
        follow_up = next(item for item in result.results if item.case.case_id == "consumed-product-return-follow-up")

        check_names = [check.name for check in follow_up.checks]
        self.assertIn("response_contains:order number", check_names)
        self.assertIn("response_excludes:duplicate", check_names)
        self.assertTrue(follow_up.passed)

    def test_builds_ci_friendly_eval_report(self) -> None:
        result = run_support_triage_eval_suite()
        report = build_eval_report(result)

        self.assertEqual(report["suite_id"], "support-triage-core")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["passed"], 11)
        self.assertEqual(report["failed_cases"], [])
        self.assertIn("Status: passed", format_eval_report(report))

    def test_eval_report_groups_failed_checks_by_category(self) -> None:
        suite_result = EvalSuiteResult(
            suite_id="support-triage-core",
            name="Support triage core",
            results=[
                EvalCaseResult(
                    case=EvalCase(
                        case_id="approval-regression",
                        name="Approval regression",
                        message="refund me",
                        customer_email="customer@example.com",
                        expected_trace_status="passed",
                    ),
                    trace=Trace(
                        trace_id="trace_eval_support_triage_approval_regression",
                        workflow_name="support-triage",
                        status="passed",
                    ),
                    checks=[
                        EvalCheck("approval_required", True, False, False),
                        EvalCheck("response_excludes:duplicate", "duplicate", "duplicate charge", False),
                    ],
                )
            ],
        )

        report = build_eval_report(suite_result)
        formatted = format_eval_report(report)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failed_check_categories"], {"Governance": 1, "Response": 1})
        self.assertIn("approval-regression", formatted)
        self.assertIn("Failed check categories:", formatted)


if __name__ == "__main__":
    unittest.main()
