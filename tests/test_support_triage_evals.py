import unittest
from unittest.mock import patch

from agent_apps.customer_service.runner import OpenAIChatCompletionsClient, SupportTriageRunner, build_default_runner
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
        self.assertEqual(result.execution_mode, "deterministic")
        self.assertEqual(result.model_provider, "static")
        self.assertEqual(result.model_name, "deterministic")
        self.assertEqual(result.total, 13)
        self.assertEqual(result.passed, 13)
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
        self.assertTrue(by_case["explicit-human-escalation"].passed)
        self.assertTrue(by_case["capability-question-clarification-route"].passed)
        self.assertTrue(by_case["account-mismatch-clarification"].passed)
        human_checks = {check.name: check.actual for check in by_case["explicit-human-escalation"].checks}
        risk_checks = {check.name: check.actual for check in by_case["repeated-refund-abuse-review"].checks}
        recovery_checks = {check.name: check.actual for check in by_case["lookup-timeout-failure"].checks}
        self.assertEqual(human_checks["escalation_type"], "human_review")
        self.assertEqual(human_checks["escalation_owner"], "support_specialist")
        self.assertEqual(risk_checks["escalation_type"], "risk_review")
        self.assertEqual(risk_checks["escalation_owner"], "trust_and_safety")
        self.assertEqual(recovery_checks["escalation_type"], "technical_recovery")
        self.assertEqual(recovery_checks["escalation_owner"], "support_operations")
        self.assertEqual(by_case["consumed-product-return-follow-up"].case.conversation_history[0]["role"], "user")

    def test_eval_result_payload_excludes_raw_trace_body(self) -> None:
        payload = run_support_triage_eval_suite().to_dict()

        self.assertEqual(payload["passed"], 13)
        self.assertEqual(payload["execution_mode"], "deterministic")
        self.assertEqual(payload["model_provider"], "static")
        self.assertEqual(payload["results"][0]["trace_id"], "trace_eval_support_triage_duplicate_charge_refund")
        self.assertNotIn("trace", payload["results"][0])
        self.assertEqual(payload["results"][0]["model_events"], [])
        self.assertTrue(all(check["passed"] for check in payload["results"][0]["checks"]))

    def test_eval_cases_include_multi_turn_quality_checks(self) -> None:
        result = run_support_triage_eval_suite()
        follow_up = next(item for item in result.results if item.case.case_id == "consumed-product-return-follow-up")

        check_names = [check.name for check in follow_up.checks]
        self.assertIn("investigation_evidence:order", check_names)
        self.assertIn("investigation_evidence:order_owner", check_names)
        self.assertIn("response_contains:order number", check_names)
        self.assertIn("response_excludes:duplicate", check_names)
        self.assertTrue(follow_up.passed)

    def test_eval_cases_include_escalation_quality_checks(self) -> None:
        result = run_support_triage_eval_suite()
        by_case = {case_result.case.case_id: case_result for case_result in result.results}

        for case_id in ("explicit-human-escalation", "repeated-refund-abuse-review", "lookup-timeout-failure"):
            check_names = {check.name for check in by_case[case_id].checks}
            self.assertIn("escalation_type", check_names)
            self.assertIn("escalation_owner", check_names)
            self.assertIn("escalation_reason", check_names)
            self.assertTrue(by_case[case_id].passed)

    def test_builds_ci_friendly_eval_report(self) -> None:
        result = run_support_triage_eval_suite()
        report = build_eval_report(result)

        self.assertEqual(report["suite_id"], "support-triage-core")
        self.assertEqual(report["execution_mode"], "deterministic")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["passed"], 13)
        self.assertEqual(report["failed_cases"], [])
        self.assertEqual(report["improvement_plan"], [])
        self.assertIn("Status: passed", format_eval_report(report))
        self.assertIn("Mode: deterministic (static/deterministic)", format_eval_report(report))

    def test_llm_eval_mode_uses_configured_runner_and_metadata(self) -> None:
        calls: list[bool] = []

        def make_runner():
            calls.append(True)
            return build_default_runner(use_openai=False)

        with patch.dict("os.environ", {"LLM_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-test"}, clear=True):
            result = run_support_triage_eval_suite(
                execution_mode="llm",
                runner_factory=make_runner,
                trace_id_prefix="trace_eval_support_triage_llm_test",
            )

        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.model_provider, "gemini")
        self.assertEqual(result.model_name, "gemini-test")
        self.assertEqual(len(calls), 13)
        self.assertTrue(result.results[0].trace.trace_id.startswith("trace_eval_support_triage_llm_test_"))

    def test_llm_eval_mode_records_model_fallback_in_trace_spans(self) -> None:
        calls: list[str] = []
        outputs = [
            '{"route":"triage","handoff_reason":"billing request needs triage"}',
            '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
            '{"required_evidence":["customer","charge"],"reason":"Duplicate billing requires customer and charge evidence."}',
            '{"retrieval_query":"duplicate_charge_refund","reason":"duplicate charge policy applies"}',
            '{"action_type":"refund_review","reason":"Review duplicate charge."}',
            '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_refund_duplicate_charge"]}',
            "I found the duplicate charge and created a refund review.",
        ]

        def post_json(url: str, *, headers: dict, json: dict, timeout: float) -> dict:
            calls.append(json["model"])
            if json["model"] == "gemini-primary":
                raise RuntimeError("LLM provider request failed with HTTP 503: UNAVAILABLE")
            return {
                "choices": [{"message": {"content": outputs.pop(0)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

        def make_runner() -> SupportTriageRunner:
            return SupportTriageRunner(
                llm_client=OpenAIChatCompletionsClient(
                    api_key="test-key",
                    model="gemini-primary",
                    base_url="http://llm.test/v1",
                    post_json=post_json,
                ),
                use_llm_agents=True,
            )

        with patch.dict("os.environ", {"LLM_PROVIDER": "gemini", "GEMINI_FALLBACK_MODELS": "gemini-fallback"}, clear=True):
            with patch("agenttrace.evals.support_triage.SUPPORT_TRIAGE_EVAL_CASES", [SUPPORT_TRIAGE_EVAL_CASES[0]]):
                result = run_support_triage_eval_suite(
                    execution_mode="llm",
                    runner_factory=make_runner,
                    trace_id_prefix="trace_eval_support_triage_llm_fallback",
                )

        triage = next(span for span in result.results[0].trace.spans if span.name == "Triage Agent")
        response = next(span for span in result.results[0].trace.spans if span.name == "Customer Response Generator")

        self.assertEqual(result.total, 1)
        self.assertEqual(calls[:2], ["gemini-primary", "gemini-fallback"])
        self.assertEqual(triage.span_data["model"], "gemini-fallback")
        self.assertTrue(triage.span_data["model_fallback_used"])
        self.assertEqual(triage.span_data["model_attempts"][0]["model"], "gemini-primary")
        self.assertEqual(response.span_data["model"], "gemini-fallback")
        self.assertEqual(result.results[0].to_dict()["model_events"][0]["model"], "gemini-fallback")
        self.assertTrue(result.results[0].to_dict()["model_events"][0]["fallback_used"])

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
                        EvalCheck("escalation_owner", "trust_and_safety", "support_specialist", False),
                        EvalCheck("response_excludes:duplicate", "duplicate", "duplicate charge", False),
                    ],
                )
            ],
        )

        report = build_eval_report(suite_result)
        formatted = format_eval_report(report)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failed_check_categories"], {"Governance": 1, "Escalation": 1, "Response": 1})
        self.assertEqual([item["category"] for item in report["improvement_plan"]], ["Escalation", "Governance", "Response"])
        self.assertEqual(report["improvement_plan"][0]["owner_area"], "human handoff routing and escalation ownership")
        self.assertEqual(report["improvement_plan"][0]["cases"][0]["case_id"], "approval-regression")
        self.assertIn("agent_apps/customer_service/runner.py", report["improvement_plan"][0]["suggested_files"])
        self.assertIn("approval-regression", formatted)
        self.assertIn("Failed check categories:", formatted)
        self.assertIn("Improvement workflow:", formatted)
        self.assertIn("owner=human handoff routing and escalation ownership", formatted)


if __name__ == "__main__":
    unittest.main()
