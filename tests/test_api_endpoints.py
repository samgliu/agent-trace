import unittest
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local env may not have FastAPI installed yet.
    TestClient = None  # type: ignore[assignment]

from agenttrace.core.importer import load_trace_file
from agenttrace.core.models import Span, Trace
from agenttrace.storage.sqlite import SQLiteTraceStore


@unittest.skipIf(TestClient is None, "FastAPI is not installed")
class ApiEndpointsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_live_span_delay = os.environ.get("AGENTTRACE_LIVE_SPAN_DELAY_SECONDS")
        self.previous_auth_env = {
            name: os.environ.get(name)
            for name in [
                "AGENTTRACE_AUTH_ENABLED",
                "AGENTTRACE_ADMIN_TOKEN",
                "AGENTTRACE_API_TOKEN",
                "AGENTTRACE_OPERATOR_TOKEN",
                "AGENTTRACE_VIEWER_TOKEN",
            ]
        }
        os.environ["AGENTTRACE_LIVE_SPAN_DELAY_SECONDS"] = "0.01"
        os.environ["AGENTTRACE_AUTH_ENABLED"] = "false"
        os.environ.pop("AGENTTRACE_ADMIN_TOKEN", None)
        os.environ.pop("AGENTTRACE_API_TOKEN", None)
        os.environ.pop("AGENTTRACE_OPERATOR_TOKEN", None)
        os.environ.pop("AGENTTRACE_VIEWER_TOKEN", None)
        self.temp_dir = TemporaryDirectory()
        self.store = SQLiteTraceStore(Path(self.temp_dir.name) / "agenttrace.db")
        self.store.initialize()
        self.trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))
        self.store.save_trace(self.trace)
        from agenttrace.api.main import create_app

        self.client = TestClient(create_app(self.store))

    def tearDown(self) -> None:
        if self.previous_live_span_delay is None:
            os.environ.pop("AGENTTRACE_LIVE_SPAN_DELAY_SECONDS", None)
        else:
            os.environ["AGENTTRACE_LIVE_SPAN_DELAY_SECONDS"] = self.previous_live_span_delay
        for name, value in self.previous_auth_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp_dir.cleanup()

    def test_health(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_auth_status_is_public_and_disabled_by_default(self) -> None:
        response = self.client.get("/auth/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"enabled": False, "authenticated": True, "role": "admin"})

    def test_auth_enabled_requires_login_for_protected_routes(self) -> None:
        from agenttrace.api.main import create_app

        with patch.dict("os.environ", {"AGENTTRACE_AUTH_ENABLED": "true", "AGENTTRACE_ADMIN_TOKEN": "secret"}, clear=False):
            client = TestClient(create_app(self.store))

        health_response = client.get("/health")
        protected_response = client.get("/dashboard/summary")
        failed_login_response = client.post("/auth/login", json={"token": "wrong"})
        login_response = client.post("/auth/login", json={"token": "secret"})
        authenticated_response = client.get("/dashboard/summary", headers={"authorization": "Bearer secret"})

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(protected_response.status_code, 401)
        self.assertEqual(failed_login_response.status_code, 401)
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("agenttrace_session", login_response.cookies)
        self.assertNotEqual(login_response.cookies["agenttrace_session"], "secret")
        self.assertIn(".", login_response.cookies["agenttrace_session"])
        self.assertEqual(authenticated_response.status_code, 200)

    def test_auth_roles_limit_approval_mutations(self) -> None:
        from agenttrace.api.main import create_app

        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)
        env = {
            "AGENTTRACE_AUTH_ENABLED": "true",
            "AGENTTRACE_ADMIN_TOKEN": "admin-secret",
            "AGENTTRACE_OPERATOR_TOKEN": "operator-secret",
            "AGENTTRACE_VIEWER_TOKEN": "viewer-secret",
        }

        with patch.dict("os.environ", env, clear=False):
            viewer_client = TestClient(create_app(self.store))
            operator_client = TestClient(create_app(self.store))
            admin_client = TestClient(create_app(self.store))

        viewer_read = viewer_client.get(
            f"/traces/{trace.trace_id}",
            headers={"authorization": "Bearer viewer-secret"},
        )
        viewer_approval = viewer_client.post(
            f"/traces/{trace.trace_id}/approvals/span_approval_failure/approve",
            headers={"authorization": "Bearer viewer-secret"},
        )
        operator_approval = operator_client.post(
            f"/traces/{trace.trace_id}/approvals/span_approval_failure/approve",
            headers={"authorization": "Bearer operator-secret"},
        )
        admin_approval = admin_client.post(
            f"/traces/{trace.trace_id}/approvals/span_approval_failure/revert",
            headers={"authorization": "Bearer admin-secret"},
        )

        self.assertEqual(viewer_read.status_code, 200)
        self.assertEqual(viewer_approval.status_code, 403)
        self.assertEqual(viewer_approval.json()["detail"], "Insufficient role for this action.")
        self.assertEqual(operator_approval.status_code, 200)
        operator_payload = operator_approval.json()
        self.assertEqual(operator_payload["span_data"]["decision_actor"]["type"], "token_role")
        self.assertEqual(operator_payload["span_data"]["decision_actor"]["id"], "operator")
        self.assertEqual(operator_payload["span_data"]["decision_actor"]["display_name"], "Operator")
        self.assertEqual(operator_payload["span_data"]["decision_actor"]["role"], "operator")
        self.assertEqual(operator_payload["span_data"]["decision_source"], "dashboard")
        self.assertEqual(operator_payload["span_data"]["decision_action"], "approved")
        self.assertEqual(operator_payload["span_data"]["approved_by"], "Operator")
        self.assertIsNotNone(operator_payload["span_data"]["decision_at"])
        self.assertEqual(admin_approval.status_code, 200)

    def test_list_evals(self) -> None:
        response = self.client.get("/evals")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["suites"][0]["suite_id"], "support-triage-core")
        self.assertEqual(payload["suites"][0]["case_count"], 13)

    def test_run_support_triage_evals_saves_eval_traces(self) -> None:
        response = self.client.post("/evals/support-triage/run")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("run_id", payload)
        self.assertEqual(payload["suite_id"], "support-triage-core")
        self.assertEqual(payload["execution_mode"], "deterministic")
        self.assertEqual(payload["model_provider"], "static")
        self.assertEqual(payload["passed"], 13)
        self.assertEqual(payload["failed"], 0)
        history_response = self.client.get("/eval-runs")
        detail_response = self.client.get(f"/eval-runs/{payload['run_id']}")
        trace_response = self.client.get("/traces/trace_eval_support_triage_annual_refund_approval")
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json()["items"][0]["run_id"], payload["run_id"])
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["results"][0]["case_id"], "duplicate-charge-refund")
        self.assertEqual(trace_response.status_code, 200)
        trace = trace_response.json()
        self.assertEqual(trace["status"], "recovered")
        self.assertEqual(trace["metadata"]["eval_suite_id"], "support-triage-core")
        self.assertEqual(trace["metadata"]["eval_execution_mode"], "deterministic")
        self.assertEqual(trace["metadata"]["source_kind"], "eval_run")

    def test_run_support_triage_evals_supports_llm_mode_metadata(self) -> None:
        from agent_apps.customer_service.runner import build_default_runner

        calls: list[dict[str, object]] = []

        def fake_build_default_runner(*, use_openai: bool = False, openai_api: str = "chat_completions"):
            calls.append({"use_openai": use_openai, "openai_api": openai_api})
            return build_default_runner(use_openai=False)

        with patch("agenttrace.evals.support_triage.build_default_runner", side_effect=fake_build_default_runner):
            with patch.dict("os.environ", {"LLM_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-test"}, clear=True):
                response = self.client.post("/evals/support-triage/run?mode=llm")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "llm")
        self.assertEqual(payload["model_provider"], "gemini")
        self.assertEqual(payload["model_name"], "gemini-test")
        self.assertEqual(calls[0], {"use_openai": True, "openai_api": "chat_completions"})
        trace_response = self.client.get("/traces/trace_eval_support_triage_llm_annual_refund_approval")
        self.assertEqual(trace_response.status_code, 200)
        self.assertEqual(trace_response.json()["metadata"]["eval_execution_mode"], "llm")

    def test_eval_comparison_pairs_latest_deterministic_and_llm_runs(self) -> None:
        for trace_id in ("trace_eval_det_case", "trace_eval_llm_case"):
            self.store.save_trace(Trace(trace_id=trace_id, workflow_name="support-triage", status="passed"))

        def eval_payload(*, mode: str, trace_id: str, passed: bool) -> dict[str, object]:
            return {
                "suite_id": "support-triage-core",
                "name": "Support triage core",
                "execution_mode": mode,
                "model_provider": "static" if mode == "deterministic" else "gemini",
                "model_name": "deterministic" if mode == "deterministic" else "gemini-test",
                "total": 1,
                "passed": 1 if passed else 0,
                "failed": 0 if passed else 1,
                "pass_rate": 1.0 if passed else 0.0,
                "results": [
                    {
                        "case_id": "duplicate-charge-refund",
                        "name": "Duplicate charge refund",
                        "trace_id": trace_id,
                        "passed": passed,
                        "score": 1.0 if passed else 0.5,
                        "checks": [
                            {"name": "response_excludes:duplicate", "expected": "no duplicate", "actual": "duplicate", "passed": passed}
                        ],
                    }
                ],
            }

        self.store.save_eval_run(
            eval_payload(mode="deterministic", trace_id="trace_eval_det_case", passed=True),
            run_id="eval_det",
        )
        self.store.save_eval_run(
            eval_payload(mode="llm", trace_id="trace_eval_llm_case", passed=False),
            run_id="eval_llm",
        )

        response = self.client.get("/eval-runs/support-triage/comparison")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["deterministic_run"]["run_id"], "eval_det")
        self.assertEqual(payload["llm_run"]["model_provider"], "gemini")
        self.assertEqual(payload["pass_rate_delta"], -1.0)
        self.assertEqual(payload["llm_regressions"][0]["case_id"], "duplicate-charge-refund")

    def test_support_triage_eval_comparison_skips_degraded_llm_run(self) -> None:
        def eval_payload(
            *,
            mode: str,
            trace_id: str,
            passed: bool,
            status: str | None = None,
            error: str | None = None,
        ) -> dict[str, object]:
            return {
                "suite_id": "support-triage-core",
                "name": "Support triage core",
                "execution_mode": mode,
                "model_provider": "static" if mode == "deterministic" else "gemini",
                "model_name": "deterministic" if mode == "deterministic" else "gemini-test",
                "status": status,
                "error": error,
                "total": 1,
                "passed": 1 if passed else 0,
                "failed": 0 if passed else 1,
                "pass_rate": 1.0 if passed else 0.0,
                "results": [
                    {
                        "case_id": "duplicate-charge-refund",
                        "name": "Duplicate charge refund",
                        "trace_id": trace_id,
                        "passed": passed,
                        "score": 1.0 if passed else 0.5,
                        "checks": [
                            {"name": "action_type", "expected": "refund_review", "actual": "clarification_request", "passed": passed}
                        ],
                    }
                ],
            }

        self.store.save_eval_run(
            eval_payload(mode="deterministic", trace_id="trace_eval_det_case", passed=True),
            run_id="eval_det",
        )
        self.store.save_eval_run(
            eval_payload(
                mode="llm",
                trace_id="trace_eval_llm_case",
                passed=False,
                status="degraded",
                error="LLM provider request failed with HTTP 429: quota exceeded",
            ),
            run_id="eval_llm",
        )

        response = self.client.get("/eval-runs/support-triage/comparison")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded_llm")
        self.assertIsNone(payload["pass_rate_delta"])
        self.assertEqual(payload["llm_regressions"], [])

    def test_support_triage_eval_failure_trends_aggregate_failed_check_categories(self) -> None:
        self.store.save_eval_run(
            {
                "suite_id": "support-triage-core",
                "name": "Support triage core",
                "execution_mode": "llm",
                "model_provider": "gemini",
                "model_name": "gemini-test",
                "status": "completed",
                "total": 1,
                "passed": 0,
                "failed": 1,
                "pass_rate": 0.0,
                "created_at": "2026-05-02T00:00:00Z",
                "results": [
                    {
                        "case_id": "duplicate-charge-refund",
                        "name": "Duplicate charge refund",
                        "trace_id": "trace_eval_trend_llm",
                        "passed": False,
                        "score": 0.5,
                        "checks": [
                            {"name": "action_type", "expected": "refund_review", "actual": "clarification_request", "passed": False},
                            {"name": "evidence_id:cus_123", "expected": "includes cus_123", "actual": [], "passed": False},
                        ],
                    }
                ],
            },
            run_id="eval_trend_llm",
        )

        response = self.client.get("/eval-runs/support-triage/failure-trends?mode=llm")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "llm")
        self.assertEqual(payload["totals"]["Routing"], 1)
        self.assertEqual(payload["totals"]["Evidence"], 1)
        self.assertEqual(payload["points"][0]["run_id"], "eval_trend_llm")
        self.assertEqual(payload["points"][0]["categories"]["Routing"], 1)

    def test_support_triage_eval_failure_trends_exclude_provider_failed_runs(self) -> None:
        for run_id, status, error in [
            ("eval_quality_failure", "failed", None),
            ("eval_provider_failure", "failed", "LLM provider request failed with HTTP 500: upstream error"),
        ]:
            self.store.save_eval_run(
                {
                    "suite_id": "support-triage-core",
                    "name": "Support triage core",
                    "execution_mode": "llm",
                    "model_provider": "gemini",
                    "model_name": "gemini-test",
                    "status": status,
                    "error": error,
                    "total": 1,
                    "passed": 0,
                    "failed": 1,
                    "pass_rate": 0.0,
                    "created_at": "2026-05-02T00:00:00Z" if run_id == "eval_quality_failure" else "2026-05-03T00:00:00Z",
                    "results": [
                        {
                            "case_id": "duplicate-charge-refund",
                            "name": "Duplicate charge refund",
                            "trace_id": f"trace_{run_id}",
                            "passed": False,
                            "score": 0.0,
                            "checks": [
                                {"name": "action_type", "expected": "refund_review", "actual": "clarification_request", "passed": False},
                            ],
                        }
                    ],
                },
                run_id=run_id,
            )

        response = self.client.get("/eval-runs/support-triage/failure-trends?mode=llm&limit=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([point["run_id"] for point in payload["points"]], ["eval_quality_failure"])
        self.assertEqual(payload["totals"]["Routing"], 1)

    def test_llm_eval_provider_failure_returns_clean_error(self) -> None:
        with patch(
            "agenttrace.api.routes.evals.run_support_triage_eval_suite",
            side_effect=RuntimeError("LLM provider request failed with HTTP 500: upstream internal error"),
        ):
            response = self.client.post("/evals/support-triage/run?mode=llm")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "LLM provider request failed with HTTP 500: upstream internal error")

    def test_llm_eval_missing_key_returns_configuration_error(self) -> None:
        with patch(
            "agenttrace.api.routes.evals.run_support_triage_eval_suite",
            side_effect=RuntimeError("LLM provider 'gemini' is not configured: missing API key."),
        ):
            response = self.client.post("/evals/support-triage/run?mode=llm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("missing API key", response.json()["detail"])

    def test_async_llm_eval_run_persists_progress(self) -> None:
        from agenttrace.evals.support_triage import EvalCaseResult, EvalCheck, SUPPORT_TRIAGE_EVAL_CASES

        def fake_run_case(case, **_kwargs):
            return EvalCaseResult(
                case=case,
                trace=Trace(
                    trace_id=f"trace_eval_support_triage_llm_{case.case_id.replace('-', '_')}",
                    workflow_name="support-triage",
                    status="passed",
                ),
                checks=[EvalCheck("trace_status", "passed", "passed", True)],
            )

        with patch("agenttrace.api.routes.evals.SUPPORT_TRIAGE_EVAL_CASES", SUPPORT_TRIAGE_EVAL_CASES[:1]):
            with patch("agenttrace.api.eval_runs.run_support_triage_eval_case", side_effect=fake_run_case):
                response = self.client.post("/evals/support-triage/run/async?mode=llm")
                self.assertEqual(response.status_code, 200)
                run = response.json()
                self.assertEqual(run["status"], "running")
                run_id = run["run_id"]
                completed = None
                for _ in range(20):
                    detail = self.client.get(f"/eval-runs/{run_id}").json()
                    if detail["status"] != "running":
                        completed = detail
                        break
                    time.sleep(0.01)

        assert completed is not None
        self.assertEqual(completed["status"], "passed")
        self.assertEqual(completed["execution_mode"], "llm")
        self.assertEqual(completed["passed"], 1)
        self.assertEqual(completed["results"][0]["case_id"], SUPPORT_TRIAGE_EVAL_CASES[0].case_id)

    def test_async_llm_eval_run_marks_provider_quota_failure_degraded(self) -> None:
        from agenttrace.evals.support_triage import SUPPORT_TRIAGE_EVAL_CASES

        with patch("agenttrace.api.routes.evals.SUPPORT_TRIAGE_EVAL_CASES", SUPPORT_TRIAGE_EVAL_CASES[:1]):
            with patch(
                "agenttrace.api.eval_runs.run_support_triage_eval_case",
                side_effect=RuntimeError("LLM provider request failed with HTTP 429: quota exceeded"),
            ):
                response = self.client.post("/evals/support-triage/run/async?mode=llm")
                self.assertEqual(response.status_code, 200)
                run_id = response.json()["run_id"]
                completed = None
                for _ in range(20):
                    detail = self.client.get(f"/eval-runs/{run_id}").json()
                    if detail["status"] != "running":
                        completed = detail
                        break
                    time.sleep(0.01)

        assert completed is not None
        self.assertEqual(completed["status"], "degraded")
        self.assertIn("HTTP 429", completed["error"])
        self.assertEqual(completed["failed"], 0)

    def test_resume_degraded_llm_eval_run_skips_completed_cases(self) -> None:
        from agenttrace.evals.support_triage import EvalCaseResult, EvalCheck, SUPPORT_TRIAGE_EVAL_CASES

        calls: list[str] = []
        cases = SUPPORT_TRIAGE_EVAL_CASES[:2]

        def fake_run_case(case, **_kwargs):
            calls.append(case.case_id)
            if case.case_id == cases[1].case_id and calls.count(case.case_id) == 1:
                raise RuntimeError("LLM provider request failed with HTTP 429: quota exceeded")
            return EvalCaseResult(
                case=case,
                trace=Trace(
                    trace_id=f"trace_eval_support_triage_llm_{case.case_id.replace('-', '_')}",
                    workflow_name="support-triage",
                    status="passed",
                ),
                checks=[EvalCheck("trace_status", "passed", "passed", True)],
            )

        with patch("agenttrace.api.routes.evals.SUPPORT_TRIAGE_EVAL_CASES", cases):
            with patch("agenttrace.api.eval_runs.run_support_triage_eval_case", side_effect=fake_run_case):
                response = self.client.post("/evals/support-triage/run/async?mode=llm")
                self.assertEqual(response.status_code, 200)
                run_id = response.json()["run_id"]
                degraded = None
                for _ in range(20):
                    detail = self.client.get(f"/eval-runs/{run_id}").json()
                    if detail["status"] == "degraded":
                        degraded = detail
                        break
                    time.sleep(0.01)
                assert degraded is not None
                self.assertEqual([result["case_id"] for result in degraded["results"]], [cases[0].case_id])

                resume_response = self.client.post(f"/eval-runs/{run_id}/resume")
                self.assertEqual(resume_response.status_code, 200)
                completed = None
                for _ in range(20):
                    detail = self.client.get(f"/eval-runs/{run_id}").json()
                    if detail["status"] != "running":
                        completed = detail
                        break
                    time.sleep(0.01)

        assert completed is not None
        self.assertEqual(completed["status"], "passed")
        self.assertEqual([result["case_id"] for result in completed["results"]], [cases[0].case_id, cases[1].case_id])
        self.assertEqual(calls, [cases[0].case_id, cases[1].case_id, cases[1].case_id])

    def test_resume_degraded_llm_eval_run_retries_saved_provider_error_cases(self) -> None:
        from agenttrace.evals.support_triage import EvalCaseResult, EvalCheck, SUPPORT_TRIAGE_EVAL_CASES

        cases = SUPPORT_TRIAGE_EVAL_CASES[:2]
        self.store.save_trace(Trace(trace_id="trace_retry_ok", workflow_name="support-triage", status="passed"))
        self.store.save_trace(Trace(trace_id="trace_retry_rate_limited", workflow_name="support-triage", status="failed"))
        self.store.save_eval_run(
            {
                "suite_id": "support-triage-core",
                "name": "Support triage core",
                "execution_mode": "llm",
                "model_provider": "gemini",
                "model_name": "gemini-test",
                "status": "degraded",
                "error": "LLM provider request failed with HTTP 429: quota exceeded",
                "total": 2,
                "passed": 1,
                "failed": 1,
                "pass_rate": 0.5,
                "results": [
                    {
                        "case_id": cases[0].case_id,
                        "name": cases[0].name,
                        "trace_id": "trace_retry_ok",
                        "passed": True,
                        "score": 1.0,
                        "checks": [{"name": "trace_status", "expected": "passed", "actual": "passed", "passed": True}],
                    },
                    {
                        "case_id": cases[1].case_id,
                        "name": cases[1].name,
                        "trace_id": "trace_retry_rate_limited",
                        "passed": False,
                        "score": 0.0,
                        "checks": [{"name": "trace_status", "expected": "passed", "actual": "failed", "passed": False}],
                        "model_events": [
                            {
                                "agent": "Action Agent",
                                "attempts": [
                                    {
                                        "model": "gemini-test",
                                        "error": "LLM provider request failed with HTTP 429: quota exceeded",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
            run_id="eval_retry_provider_error",
        )
        calls: list[str] = []

        def fake_run_case(case, **_kwargs):
            calls.append(case.case_id)
            return EvalCaseResult(
                case=case,
                trace=Trace(
                    trace_id=f"trace_eval_support_triage_llm_{case.case_id.replace('-', '_')}",
                    workflow_name="support-triage",
                    status="passed",
                ),
                checks=[EvalCheck("trace_status", "passed", "passed", True)],
            )

        with patch("agenttrace.api.routes.evals.SUPPORT_TRIAGE_EVAL_CASES", cases):
            with patch("agenttrace.api.eval_runs.run_support_triage_eval_case", side_effect=fake_run_case):
                response = self.client.post("/eval-runs/eval_retry_provider_error/resume")
                self.assertEqual(response.status_code, 200)
                running = response.json()
                self.assertEqual([result["case_id"] for result in running["results"]], [cases[0].case_id])

                completed = None
                for _ in range(20):
                    detail = self.client.get("/eval-runs/eval_retry_provider_error").json()
                    if detail["status"] != "running":
                        completed = detail
                        break
                    time.sleep(0.01)

        assert completed is not None
        self.assertEqual(completed["status"], "passed")
        self.assertEqual([result["case_id"] for result in completed["results"]], [cases[0].case_id, cases[1].case_id])
        self.assertEqual(calls, [cases[1].case_id])

    def test_resume_historical_provider_api_failure_reruns_failed_completed_cases(self) -> None:
        from agenttrace.evals.support_triage import EvalCaseResult, EvalCheck, SUPPORT_TRIAGE_EVAL_CASES

        cases = SUPPORT_TRIAGE_EVAL_CASES[:2]
        self.store.save_eval_run(
            {
                "suite_id": "support-triage-core",
                "name": "Support triage core",
                "execution_mode": "llm",
                "model_provider": "gemini",
                "model_name": "gemini-test",
                "status": "failed",
                "error": "LLM provider request failed with HTTP 500: upstream internal error",
                "total": 2,
                "passed": 0,
                "failed": 2,
                "pass_rate": 0.0,
                "results": [
                    {
                        "case_id": case.case_id,
                        "name": case.name,
                        "trace_id": f"trace_old_{case.case_id}",
                        "passed": False,
                        "score": 0.0,
                        "checks": [{"name": "trace_status", "expected": "passed", "actual": "failed", "passed": False}],
                    }
                    for case in cases
                ],
            },
            run_id="eval_historical_provider_failure",
        )
        calls: list[str] = []

        def fake_run_case(case, **_kwargs):
            calls.append(case.case_id)
            return EvalCaseResult(
                case=case,
                trace=Trace(
                    trace_id=f"trace_rerun_{case.case_id}",
                    workflow_name="support-triage",
                    status="passed",
                ),
                checks=[EvalCheck("trace_status", "passed", "passed", True)],
            )

        with patch("agenttrace.api.routes.evals.SUPPORT_TRIAGE_EVAL_CASES", cases):
            with patch("agenttrace.api.eval_runs.SUPPORT_TRIAGE_EVAL_CASES", cases):
                with patch("agenttrace.api.eval_runs.run_support_triage_eval_case", side_effect=fake_run_case):
                    response = self.client.post("/eval-runs/eval_historical_provider_failure/resume")
                    self.assertEqual(response.status_code, 200)
                    completed = None
                    for _ in range(20):
                        detail = self.client.get("/eval-runs/eval_historical_provider_failure").json()
                        if detail["status"] != "running":
                            completed = detail
                            break
                        time.sleep(0.01)

        assert completed is not None
        self.assertEqual(completed["status"], "passed")
        self.assertEqual(completed["pass_rate"], 1.0)
        self.assertEqual(calls, [cases[0].case_id, cases[1].case_id])

    def test_get_missing_eval_run_returns_404(self) -> None:
        response = self.client.get("/eval-runs/missing")

        self.assertEqual(response.status_code, 404)

    def test_cors_allows_local_dashboard(self) -> None:
        response = self.client.options(
            "/traces",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_list_traces(self) -> None:
        response = self.client.get("/traces")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["limit"], 50)
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(payload["items"][0]["trace_id"], self.trace.trace_id)
        self.assertEqual(payload["items"][0]["span_count"], 10)
        self.assertEqual(payload["items"][0]["approval_pending_count"], 0)

    def test_list_traces_filters_by_pending_approval(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get("/traces?approval_status=pending")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], trace.trace_id)
        self.assertEqual(payload["items"][0]["approval_pending_count"], 1)
        self.assertEqual(payload["items"][0]["status"], "passed")
        self.assertEqual(payload["items"][0]["grounding_status"], "recovered")

    def test_list_traces_filters_by_workflow_status_and_date(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get(
            "/traces?workflow_name=support-triage&status=passed&started_after=2026-05-01T00:00:00Z"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)

    def test_list_traces_filters_by_source(self) -> None:
        trace = load_trace_file(
            Path("examples/openai_agents/sample_trace_export.json"),
            trace_format="openai-agents",
        )
        self.store.save_trace(trace)

        response = self.client.get("/traces?source_format=openai-agents&source_kind=trace_export")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], "oa_trace_support_triage_export")
        self.assertEqual(payload["items"][0]["source_format"], "openai-agents")
        self.assertEqual(payload["items"][0]["source_kind"], "trace_export")

    def test_list_traces_filters_by_chat_session(self) -> None:
        self.trace.metadata["chat_session_id"] = "chat_1"
        self.store.save_trace(self.trace)
        other_trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        other_trace.metadata["chat_session_id"] = "chat_2"
        self.store.save_trace(other_trace)

        response = self.client.get("/traces?chat_session_id=chat_1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], self.trace.trace_id)

    def test_trace_summaries_filters_by_ids(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_tool_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get(f"/trace-summaries?trace_ids={trace.trace_id},missing,{self.trace.trace_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual({item["trace_id"] for item in payload}, {self.trace.trace_id, trace.trace_id})

    def test_list_traces_filters_by_errors(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_tool_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get("/traces?has_errors=true")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], "trace_support_triage_tool_failure")
        self.assertEqual(payload["items"][0]["error_count"], 1)

    def test_list_traces_filters_by_escalation(self) -> None:
        trace = Trace(
            trace_id="trace_escalation_api",
            workflow_name="support-triage",
            status="recovered",
            spans=[
                Span(
                    span_id="span_escalation",
                    trace_id="trace_escalation_api",
                    name="Escalation Agent",
                    span_type="agent",
                    output={
                        "escalation_type": "risk_review",
                        "reason": "Risk controls require review.",
                        "handoff_summary": "Review refund risk signals.",
                        "next_owner": "trust_and_safety",
                        "evidence": ["cus_risk", "policy_refund_duplicate_charge"],
                    },
                    span_data={
                        "agent_role": "escalation",
                        "escalation_type": "risk_review",
                        "next_owner": "trust_and_safety",
                    },
                )
            ],
        )
        self.store.save_trace(trace)

        response = self.client.get("/traces?has_escalation=true&escalation_type=risk_review&escalation_owner=trust_and_safety")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["trace_id"], "trace_escalation_api")
        self.assertEqual(payload["items"][0]["escalation_count"], 1)
        self.assertEqual(payload["items"][0]["escalation_types"], ["risk_review"])
        self.assertEqual(payload["items"][0]["escalation_next_owners"], ["trust_and_safety"])

    def test_list_workflows(self) -> None:
        response = self.client.get("/workflows")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["support-triage"])

    def test_dashboard_summary(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)
        memory_trace = Trace(
            trace_id="trace_memory_api",
            workflow_name="support-triage",
            status="passed",
            spans=[
                Span(
                    span_id="memory_read",
                    trace_id="trace_memory_api",
                    name="Read Customer Memory",
                    span_type="memory_read",
                    span_data={
                        "retrieved_memory_count": 1,
                        "memory_relevance_score": 0.42,
                        "memory_age_seconds": 86400 * 180,
                        "memory_used_in_response": False,
                    },
                )
            ],
        )
        self.store.save_trace(memory_trace)
        escalation_trace = Trace(
            trace_id="trace_escalation_summary",
            workflow_name="support-triage",
            status="recovered",
            spans=[
                Span(
                    span_id="span_escalation_summary",
                    trace_id="trace_escalation_summary",
                    name="Escalation Agent",
                    span_type="agent",
                    output={"escalation_type": "human_review", "next_owner": "support_specialist"},
                    span_data={
                        "agent_role": "escalation",
                        "escalation_type": "human_review",
                        "next_owner": "support_specialist",
                    },
                )
            ],
        )
        self.store.save_trace(escalation_trace)

        response = self.client.get("/dashboard/summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_runs"], 4)
        self.assertEqual(payload["approval_pending_count"], 1)
        self.assertEqual(payload["unsupported_claim_count"], 1)
        self.assertEqual(payload["error_count"], 0)
        self.assertEqual(payload["workflow_counts"]["support-triage"], 4)
        self.assertEqual(payload["memory_read_count"], 1)
        self.assertEqual(payload["memory_warning_count"], 3)
        self.assertEqual(payload["status_counts"]["passed"], 4)
        self.assertEqual(payload["escalation_count"], 1)
        self.assertEqual(payload["escalation_human_review_count"], 1)
        self.assertEqual(payload["escalation_type_counts"]["human_review"], 1)
        self.assertEqual(payload["escalation_owner_counts"]["support_specialist"], 1)

    def test_event_bus_streams_published_sse_events(self) -> None:
        from agenttrace.api.event_bus import EventBus

        bus = EventBus()
        stream = bus.stream()

        self.assertIn("event: connected", next(stream))
        bus.publish("trace.updated", resource_type="trace", resource_id="trace_1", trace_id="trace_1")
        frame = next(stream)

        self.assertIn("event: trace.updated", frame)
        self.assertIn('"trace_id":"trace_1"', frame)

    def test_get_trace(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trace_id"], self.trace.trace_id)
        self.assertEqual(len(payload["spans"]), 10)

    def test_trace_detail_spans_and_raw_are_redacted_by_default(self) -> None:
        trace = Trace(
            trace_id="trace_sensitive",
            workflow_name="support-triage",
            status="passed",
            metadata={"customer_email": "customer@example.com"},
            raw_payload={
                "id": "trace_sensitive",
                "customer_email": "customer@example.com",
                "message": "Call 415-555-0199 and use card 4242 4242 4242 4242.",
            },
            spans=[
                Span(
                    span_id="span_sensitive",
                    trace_id="trace_sensitive",
                    name="Customer Response Generator",
                    span_type="generation",
                    input={"message": "My email is customer@example.com"},
                    output={"reply": "We will contact customer@example.com at 415-555-0199."},
                    span_data={"model_output_text": "Card 4242 4242 4242 4242 was mentioned."},
                )
            ],
        )
        self.store.save_trace(trace)

        detail_response = self.client.get("/traces/trace_sensitive")
        spans_response = self.client.get("/traces/trace_sensitive/spans")
        raw_response = self.client.get("/traces/trace_sensitive/raw")

        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()
        self.assertTrue(detail["metadata"]["contains_pii"])
        self.assertTrue(detail["metadata"]["redaction_applied"])
        self.assertEqual(detail["metadata"]["customer_email"], "[REDACTED_EMAIL]")
        self.assertEqual(detail["spans"][0]["input"]["message"], "My email is [REDACTED_EMAIL]")
        self.assertEqual(detail["spans"][0]["span_data"]["model_output_text"], "Card [REDACTED_PAYMENT] was mentioned.")
        self.assertTrue(detail["spans"][0]["span_data"]["contains_pii"])
        self.assertEqual(spans_response.json()[0]["output"]["reply"], "We will contact [REDACTED_EMAIL] at [REDACTED_PHONE].")
        self.assertEqual(raw_response.json()["customer_email"], "[REDACTED_EMAIL]")
        self.assertEqual(raw_response.json()["message"], "Call [REDACTED_PHONE] and use card [REDACTED_PAYMENT].")

    def test_ingest_trace_span_and_lifecycle(self) -> None:
        trace_payload = {
            "trace_id": "live_trace_api",
            "workflow_name": "support-triage",
            "status": "running",
            "started_at": "2026-05-03T21:00:00Z",
            "spans": [],
        }

        trace_response = self.client.post("/traces", json=trace_payload)
        span_response = self.client.post(
            "/traces/live_trace_api/spans",
            json={
                "span_id": "span_live_supervisor",
                "name": "Supervisor Agent",
                "span_type": "agent",
                "started_at": "2026-05-03T21:00:00Z",
                "ended_at": "2026-05-03T21:00:01Z",
                "input_tokens": 10,
                "output_tokens": 5,
                "estimated_cost": 0.0001,
            },
        )
        lifecycle_response = self.client.patch(
            "/traces/live_trace_api",
            json={"status": "passed", "ended_at": "2026-05-03T21:00:04Z"},
        )

        self.assertEqual(trace_response.status_code, 200)
        self.assertEqual(trace_response.json()["metadata"]["source_format"], "agenttrace")
        self.assertEqual(trace_response.json()["metadata"]["source_kind"], "live_api")
        self.assertIn("ingested_at", trace_response.json()["metadata"])
        self.assertEqual(span_response.status_code, 200)
        self.assertEqual(lifecycle_response.status_code, 200)
        self.assertEqual(lifecycle_response.json()["status"], "passed")
        summary = self.client.get("/traces?workflow_name=support-triage&status=passed").json()
        self.assertEqual(summary["total"], 2)

    def test_ingest_trace_validates_required_trace_id(self) -> None:
        response = self.client.post("/traces", json={"workflow_name": "support-triage"})

        self.assertEqual(response.status_code, 422)

    def test_run_support_triage_workflow_persists_agent_trace(self) -> None:
        response = self.client.post(
            "/workflows/support-triage/runs",
            json={
                "trace_id": "trace_api_runner",
                "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
                "customer_email": "customer@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["trace_id"], "trace_api_runner")
        self.assertEqual(body["status"], "passed")
        self.assertEqual(body["metadata"]["source_kind"], "agent_runner")
        self.assertTrue(any(span["span_type"] == "generation" for span in body["spans"]))

        saved = self.client.get("/traces/trace_api_runner")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["metadata"]["source_format"], "agenttrace")

    def test_run_support_triage_workflow_can_delegate_to_agent_service(self) -> None:
        captured_payloads: list[dict[str, object]] = []

        def post_agent_service_json(url: str, payload: dict[str, object]) -> dict[str, object]:
            captured_payloads.append({"url": url, "payload": payload})
            return {
                "trace": Trace(
                    trace_id=str(payload["trace_id"]),
                    workflow_name="support-triage",
                    status="passed",
                    metadata={"source": "agent-service-test"},
                ).to_dict(),
                "assistant_response": "done",
            }

        with patch.dict("os.environ", {"AGENTTRACE_AGENT_SERVICE_URL": "http://agent-service.test"}):
            with patch("agenttrace.api.agent_service._post_agent_service_json", side_effect=post_agent_service_json):
                response = self.client.post(
                    "/workflows/support-triage/runs",
                    json={
                        "trace_id": "trace_api_delegated_runner",
                        "message": "Refund?",
                        "customer_email": "customer@example.com",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["trace_id"], "trace_api_delegated_runner")
        self.assertEqual(
            captured_payloads,
            [
                {
                    "url": "http://agent-service.test/runs/support-triage",
                    "payload": {
                        "message": "Refund?",
                        "customer_email": "customer@example.com",
                        "trace_id": "trace_api_delegated_runner",
                        "conversation_history": [],
                        "use_openai": False,
                        "openai_api": "chat_completions",
                    },
                }
            ],
        )

    def test_run_support_triage_workflow_returns_clean_agent_service_timeout(self) -> None:
        with patch.dict("os.environ", {"AGENTTRACE_AGENT_SERVICE_URL": "http://agent-service.test"}):
            with patch("agenttrace.api.agent_service.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
                response = self.client.post(
                    "/workflows/support-triage/runs",
                    json={
                        "trace_id": "trace_api_delegated_timeout",
                        "message": "Refund?",
                        "customer_email": "customer@example.com",
                    },
                )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["detail"], "Agent service timed out while running the workflow.")

    def test_agent_service_timeout_defaults_to_real_llm_budget(self) -> None:
        from agenttrace.api.agent_service import _agent_service_timeout_seconds

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_agent_service_timeout_seconds(), 300.0)

    def test_live_support_triage_workflow_can_be_polled_until_trace_is_ready(self) -> None:
        response = self.client.post(
            "/workflows/support-triage/runs/live",
            json={
                "trace_id": "trace_api_live_runner",
                "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
                "customer_email": "customer@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        run = response.json()
        self.assertIn(run["status"], {"pending", "running", "completed"})
        self.assertEqual(run["workflow_name"], "support-triage")
        self.assertEqual(run["trace_id"], "trace_api_live_runner")
        self.assertEqual(run["trace"]["trace_id"], "trace_api_live_runner")
        self.assertEqual(run["trace"]["status"], "running")

        completed = None
        saw_partial_trace = False
        for _ in range(20):
            poll = self.client.get(f"/workflow-runs/{run['run_id']}")
            self.assertEqual(poll.status_code, 200)
            payload = poll.json()
            if payload["status"] == "running" and 0 < len(payload["trace"]["spans"]) < 14:
                saw_partial_trace = True
            if payload["status"] == "completed":
                completed = payload
                break
            time.sleep(0.05)

        self.assertIsNotNone(completed)
        self.assertTrue(saw_partial_trace)
        self.assertEqual(completed["trace_id"], "trace_api_live_runner")
        self.assertEqual(completed["trace"]["status"], "passed")
        self.assertTrue(any(span["span_type"] == "memory_read" for span in completed["trace"]["spans"]))

    def test_live_support_triage_workflow_missing_run_returns_404(self) -> None:
        response = self.client.get("/workflow-runs/missing")

        self.assertEqual(response.status_code, 404)

    def test_live_support_triage_workflow_can_be_cancelled_and_retried(self) -> None:
        response = self.client.post(
            "/workflows/support-triage/runs/live",
            json={
                "trace_id": "trace_api_live_cancel",
                "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
                "customer_email": "customer@example.com",
            },
        )
        self.assertEqual(response.status_code, 200)
        run = response.json()

        cancel_response = self.client.post(f"/workflow-runs/{run['run_id']}/cancel")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertIn(cancel_response.json()["status"], {"cancel_requested", "cancelled"})

        cancelled = None
        for _ in range(20):
            poll = self.client.get(f"/workflow-runs/{run['run_id']}")
            self.assertEqual(poll.status_code, 200)
            payload = poll.json()
            if payload["status"] == "cancelled":
                cancelled = payload
                break
            time.sleep(0.05)

        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled["trace"]["status"], "cancelled")

        retry_response = self.client.post(f"/workflow-runs/{run['run_id']}/retry")
        self.assertEqual(retry_response.status_code, 200)
        retry = retry_response.json()
        self.assertNotEqual(retry["run_id"], run["run_id"])
        self.assertTrue(retry["trace_id"].startswith("trace_api_live_cancel_retry_"))
        self.assertEqual(retry["trace"]["status"], "running")
        self.client.post(f"/workflow-runs/{retry['run_id']}/cancel")
        self._wait_for_run_status(retry["run_id"], {"cancelled", "completed"})

    def test_live_support_triage_retry_rejects_active_run(self) -> None:
        response = self.client.post(
            "/workflows/support-triage/runs/live",
            json={
                "trace_id": "trace_api_live_retry_active",
                "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
                "customer_email": "customer@example.com",
            },
        )
        self.assertEqual(response.status_code, 200)

        retry_response = self.client.post(f"/workflow-runs/{response.json()['run_id']}/retry")

        self.assertEqual(retry_response.status_code, 400)
        self.client.post(f"/workflow-runs/{response.json()['run_id']}/cancel")
        self._wait_for_run_status(response.json()["run_id"], {"cancelled", "completed"})

    def test_live_support_triage_run_survives_app_recreation_for_retry(self) -> None:
        response = self.client.post(
            "/workflows/support-triage/runs/live",
            json={
                "trace_id": "trace_api_live_recreate",
                "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
                "customer_email": "customer@example.com",
            },
        )
        self.assertEqual(response.status_code, 200)
        run = response.json()
        self.client.post(f"/workflow-runs/{run['run_id']}/cancel")
        terminal = self._wait_for_run_status(run["run_id"], {"cancelled", "completed"})
        self.assertIn(terminal["status"], {"cancelled", "completed"})

        from agenttrace.api.main import create_app

        recreated_client = TestClient(create_app(self.store))
        saved = recreated_client.get(f"/workflow-runs/{run['run_id']}")
        retry_response = recreated_client.post(f"/workflow-runs/{run['run_id']}/retry")

        self.assertEqual(saved.status_code, 200)
        self.assertIn(saved.json()["status"], {"cancelled", "completed"})
        self.assertEqual(retry_response.status_code, 200)
        retry = retry_response.json()
        self.assertNotEqual(retry["run_id"], run["run_id"])
        recreated_client.post(f"/workflow-runs/{retry['run_id']}/cancel")
        for _ in range(20):
            poll = recreated_client.get(f"/workflow-runs/{retry['run_id']}")
            self.assertEqual(poll.status_code, 200)
            if poll.json()["status"] in {"cancelled", "completed"}:
                break
            time.sleep(0.05)

    def test_startup_reconciles_stale_running_workflow_run(self) -> None:
        self.store.save_trace(Trace(trace_id="trace_stale_running", workflow_name="support-triage", status="running"))
        run = self.store.create_workflow_run(
            run_id="run_stale_running",
            workflow_name="support-triage",
            trace_id="trace_stale_running",
            input_data={
                "message": "Refund?",
                "customer_email": "customer@example.com",
                "use_openai": False,
                "openai_api": "chat_completions",
            },
        )
        self.store.update_workflow_run(run["run_id"], status="running")

        from agenttrace.api.main import create_app

        recreated_client = TestClient(create_app(self.store))
        saved_run = recreated_client.get(f"/workflow-runs/{run['run_id']}")
        saved_trace = recreated_client.get("/traces/trace_stale_running")

        self.assertEqual(saved_run.status_code, 200)
        self.assertEqual(saved_run.json()["status"], "failed")
        self.assertEqual(saved_run.json()["error"], "API restarted before workflow completed.")
        self.assertEqual(saved_trace.json()["status"], "failed")

    def test_startup_reconciles_stale_cancel_requested_workflow_run(self) -> None:
        self.store.save_trace(Trace(trace_id="trace_stale_cancel", workflow_name="support-triage", status="running"))
        run = self.store.create_workflow_run(
            run_id="run_stale_cancel",
            workflow_name="support-triage",
            trace_id="trace_stale_cancel",
            input_data={
                "message": "Refund?",
                "customer_email": "customer@example.com",
                "use_openai": False,
                "openai_api": "chat_completions",
            },
        )
        self.store.update_workflow_run(run["run_id"], status="cancel_requested", cancel_requested=True)

        from agenttrace.api.main import create_app

        recreated_client = TestClient(create_app(self.store))
        saved_run = recreated_client.get(f"/workflow-runs/{run['run_id']}")
        saved_trace = recreated_client.get("/traces/trace_stale_cancel")
        retry_response = recreated_client.post(f"/workflow-runs/{run['run_id']}/retry")

        self.assertEqual(saved_run.status_code, 200)
        self.assertEqual(saved_run.json()["status"], "cancelled")
        self.assertEqual(saved_trace.json()["status"], "cancelled")
        self.assertEqual(retry_response.status_code, 200)
        retry = retry_response.json()
        recreated_client.post(f"/workflow-runs/{retry['run_id']}/cancel")
        for _ in range(20):
            poll = recreated_client.get(f"/workflow-runs/{retry['run_id']}")
            self.assertEqual(poll.status_code, 200)
            if poll.json()["status"] in {"cancelled", "completed"}:
                break
            time.sleep(0.05)

    def _wait_for_run_status(self, run_id: str, statuses: set[str]) -> dict:
        for _ in range(100):
            poll = self.client.get(f"/workflow-runs/{run_id}")
            self.assertEqual(poll.status_code, 200)
            payload = poll.json()
            if payload["status"] in statuses:
                return payload
            time.sleep(0.05)
        self.fail(f"Workflow run {run_id} did not reach one of {statuses}")

    def test_chat_message_runs_agent_and_links_trace(self) -> None:
        session_response = self.client.post(
            "/chat/sessions",
            json={"customer_email": "customer@example.com", "title": "Billing support"},
        )
        self.assertEqual(session_response.status_code, 200)
        session = session_response.json()

        message_response = self.client.post(
            f"/chat/sessions/{session['session_id']}/messages",
            json={"content": "I was charged twice for my Pro subscription yesterday. Can I get a refund?"},
        )

        self.assertEqual(message_response.status_code, 200)
        payload = message_response.json()
        self.assertEqual(payload["session"]["session_id"], session["session_id"])
        self.assertEqual(payload["user_message"]["role"], "user")
        self.assertEqual(payload["assistant_message"]["role"], "assistant")
        self.assertEqual(payload["assistant_message"]["trace_id"], payload["trace"]["trace_id"])
        self.assertEqual(payload["trace"]["metadata"]["chat_session_id"], session["session_id"])
        self.assertEqual(payload["trace"]["metadata"]["chat_user_message_id"], payload["user_message"]["message_id"])
        self.assertTrue(payload["assistant_message"]["content"])

        messages = self.client.get(f"/chat/sessions/{session['session_id']}/messages")
        self.assertEqual(messages.status_code, 200)
        self.assertEqual([message["role"] for message in messages.json()], ["user", "assistant"])

    def test_chat_message_returns_clean_llm_error_with_cors_header(self) -> None:
        class FailingRunner:
            def run(self, **_: object) -> None:
                raise RuntimeError("LLM provider request failed with HTTP 429.")

        session_response = self.client.post(
            "/chat/sessions",
            json={"customer_email": "customer@example.com", "title": "Billing support"},
        )
        session = session_response.json()

        with patch("agenttrace.api.agent_service.build_default_runner", return_value=FailingRunner()):
            response = self.client.post(
                f"/chat/sessions/{session['session_id']}/messages",
                json={"content": "Use configured LLM", "use_openai": True},
                headers={"Origin": "http://localhost:5173"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertEqual(response.json()["detail"], "LLM provider request failed with HTTP 429.")

    def test_chat_followup_passes_recent_history_to_runner(self) -> None:
        captured_history: list[list[dict[str, object]]] = []

        class CapturingRunner:
            def run(self, **kwargs: object) -> Trace:
                captured_history.append(list(kwargs.get("conversation_history") or []))
                return Trace(
                    trace_id=str(kwargs["trace_id"]),
                    workflow_name="support-triage",
                    status="passed",
                    metadata={"source": "test"},
                )

        session_response = self.client.post(
            "/chat/sessions",
            json={"customer_email": "customer@example.com", "title": "Billing support"},
        )
        session = session_response.json()

        with patch("agenttrace.api.agent_service.build_default_runner", return_value=CapturingRunner()):
            self.client.post(f"/chat/sessions/{session['session_id']}/messages", json={"content": "First message"})
            self.client.post(f"/chat/sessions/{session['session_id']}/messages", json={"content": "Follow-up message"})

        self.assertEqual(captured_history[0], [])
        self.assertEqual([item["role"] for item in captured_history[1]], ["user", "assistant"])
        self.assertEqual(captured_history[1][0]["content"], "First message")

    def test_chat_message_delegates_history_to_agent_service_when_configured(self) -> None:
        captured_payloads: list[dict[str, object]] = []

        def post_agent_service_json(url: str, payload: dict[str, object]) -> dict[str, object]:
            captured_payloads.append({"url": url, "payload": payload})
            return {
                "trace": Trace(
                    trace_id=str(payload["trace_id"]),
                    workflow_name="support-triage",
                    status="passed",
                    metadata={"source": "agent-service-test"},
                ).to_dict(),
                "assistant_response": "done",
            }

        session_response = self.client.post(
            "/chat/sessions",
            json={"customer_email": "customer@example.com", "title": "Billing support"},
        )
        session = session_response.json()

        with patch.dict("os.environ", {"AGENTTRACE_AGENT_SERVICE_URL": "http://agent-service.test"}):
            with patch("agenttrace.api.agent_service._post_agent_service_json", side_effect=post_agent_service_json):
                self.client.post(f"/chat/sessions/{session['session_id']}/messages", json={"content": "First"})
                response = self.client.post(
                    f"/chat/sessions/{session['session_id']}/messages",
                    json={"content": "Second"},
                )

        self.assertEqual(response.status_code, 200)
        second_payload = captured_payloads[1]["payload"]
        self.assertEqual(second_payload["message"], "Second")
        self.assertEqual(len(second_payload["conversation_history"]), 2)
        self.assertEqual(second_payload["conversation_history"][0]["content"], "First")

    def test_async_chat_message_returns_pending_assistant_message(self) -> None:
        session_response = self.client.post(
            "/chat/sessions",
            json={"customer_email": "customer@example.com", "title": "Billing support"},
        )
        session = session_response.json()

        with patch("agenttrace.api.main.start_async_chat_turn") as start_async_chat_turn:
            response = self.client.post(
                f"/chat/sessions/{session['session_id']}/messages/async",
                json={"content": "I was charged twice."},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user_message"]["role"], "user")
        self.assertEqual(payload["assistant_message"]["role"], "assistant")
        self.assertTrue(payload["assistant_message"]["metadata"]["pending"])
        self.assertEqual(payload["assistant_message"]["metadata"]["status"], "pending")
        start_async_chat_turn.assert_called_once()

        messages = self.client.get(f"/chat/sessions/{session['session_id']}/messages").json()
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertTrue(messages[1]["metadata"]["pending"])

    def test_complete_async_chat_turn_updates_assistant_message_and_trace(self) -> None:
        from agenttrace.api.chat_sessions import _complete_async_chat_turn
        from agenttrace.api.event_bus import EventBus
        from agenttrace.api.schemas import ChatMessageCreateRequest

        class PassingRunner:
            def run(self, **kwargs: object) -> Trace:
                return Trace(
                    trace_id=str(kwargs["trace_id"]),
                    workflow_name="support-triage",
                    status="passed",
                    metadata={"source": "async-test"},
                )

        session = self.store.create_chat_session(customer_email="customer@example.com")
        user_message = self.store.add_chat_message(session["session_id"], role="user", content="Refund?")
        assistant_message = self.store.add_chat_message(
            session["session_id"],
            role="assistant",
            content="Checking account, policy, and approval context",
            metadata={"status": "pending", "pending": True},
        )
        event_bus = EventBus()
        events: list[dict[str, object]] = []
        original_publish = event_bus.publish

        def capture_event(event_type: str, **payload: object) -> dict[str, object]:
            event = original_publish(event_type, **payload)
            events.append(event)
            return event

        with patch("agenttrace.api.agent_service.build_default_runner", return_value=PassingRunner()):
            with patch.object(event_bus, "publish", side_effect=capture_event):
                _complete_async_chat_turn(
                    trace_store=self.store,
                    event_bus=event_bus,
                    session=session,
                    previous_messages=[],
                    user_message=user_message,
                    assistant_message=assistant_message,
                    payload=ChatMessageCreateRequest(content="Refund?"),
                )

        messages = self.store.list_chat_messages(session["session_id"])
        self.assertEqual(messages[1]["metadata"]["status"], "complete")
        self.assertFalse(messages[1]["metadata"]["pending"])
        self.assertEqual(messages[1]["trace_id"], f"trace_chat_{user_message['message_id']}")
        trace = self.store.get_trace(messages[1]["trace_id"])
        self.assertIsNotNone(trace)
        event_types = [str(event["type"]) for event in events]
        self.assertIn("chat.turn.completed", event_types)
        self.assertNotIn("chat.message.updated", event_types)

    def test_complete_async_chat_turn_marks_provider_error_failed(self) -> None:
        from agenttrace.api.chat_sessions import _complete_async_chat_turn
        from agenttrace.api.event_bus import EventBus
        from agenttrace.api.schemas import ChatMessageCreateRequest

        class FailingRunner:
            def run(self, **_: object) -> None:
                raise RuntimeError("LLM provider request failed with HTTP 429.")

        session = self.store.create_chat_session(customer_email="customer@example.com")
        user_message = self.store.add_chat_message(session["session_id"], role="user", content="Use LLM")
        assistant_message = self.store.add_chat_message(
            session["session_id"],
            role="assistant",
            content="Checking account, policy, and approval context",
            metadata={"status": "pending", "pending": True},
        )

        with patch("agenttrace.api.agent_service.build_default_runner", return_value=FailingRunner()):
            _complete_async_chat_turn(
                trace_store=self.store,
                event_bus=EventBus(),
                session=session,
                previous_messages=[],
                user_message=user_message,
                assistant_message=assistant_message,
                payload=ChatMessageCreateRequest(content="Use LLM", use_openai=True),
            )

        messages = self.store.list_chat_messages(session["session_id"])
        self.assertEqual(messages[1]["metadata"]["status"], "failed")
        self.assertFalse(messages[1]["metadata"]["pending"])
        self.assertEqual(messages[1]["metadata"]["error"], "LLM provider request failed with HTTP 429.")

    def test_chat_message_missing_session_returns_404(self) -> None:
        response = self.client.post("/chat/sessions/missing-session/messages", json={"content": "Hello"})

        self.assertEqual(response.status_code, 404)

    def test_ingest_openai_agents_trace(self) -> None:
        with Path("examples/openai_agents/sample_trace_export.json").open("r", encoding="utf-8") as file:
            import json

            payload = json.load(file)

        response = self.client.post("/ingest/openai-agents", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["trace_id"], "oa_trace_support_triage_export")
        self.assertEqual(len(body["spans"]), 5)
        self.assertEqual(body["metadata"]["source_format"], "openai-agents")
        self.assertEqual(body["metadata"]["source_kind"], "trace_export")
        self.assertIn("ingested_at", body["metadata"])

        raw_response = self.client.get("/traces/oa_trace_support_triage_export/raw")
        self.assertEqual(raw_response.status_code, 200)
        self.assertEqual(raw_response.json()["id"], "oa_trace_support_triage_export")
        self.assertEqual(raw_response.json()["spans"][1]["type"], "model_call")

    def test_get_spans(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}/spans")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 10)
        self.assertEqual(payload[0]["name"], "Supervisor Agent")

    def test_get_metrics(self) -> None:
        response = self.client.get(f"/traces/{self.trace.trace_id}/metrics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_count"], 10)
        self.assertEqual(payload["input_tokens"], 1550)
        self.assertEqual(payload["estimated_cost"], 0.0034)

    def test_get_grounding(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.get(f"/traces/{trace.trace_id}/grounding")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "recovered")
        self.assertEqual(payload["unsupported_claim_count"], 1)
        self.assertEqual(payload["unsupported_claims"][0]["span_name"], "Validator Agent")

    def test_missing_trace_returns_404(self) -> None:
        response = self.client.get("/traces/missing-trace")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Trace not found: missing-trace")

    def test_approve_approval_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/approve")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_data"]["approval_status"], "approved")
        self.assertEqual(payload["output"]["approval_status"], "approved")
        self.assertEqual(payload["span_data"]["approved_by"], "Admin")
        self.assertIsNotNone(payload["span_data"]["approved_at"])
        self.assertEqual(payload["span_data"]["decision_actor"]["type"], "token_role")
        self.assertEqual(payload["span_data"]["decision_actor"]["id"], "admin")
        self.assertEqual(payload["span_data"]["decision_actor"]["display_name"], "Admin")
        self.assertEqual(payload["span_data"]["decision_source"], "dashboard")
        self.assertEqual(payload["span_data"]["decision_action"], "approved")
        self.assertIsNotNone(payload["span_data"]["decision_at"])
        self.assertEqual(len(payload["span_data"]["decision_history"]), 1)
        self.assertEqual(payload["span_data"]["decision_history"][0]["decision_action"], "approved")
        self.assertEqual(payload["output"]["decision_history"], payload["span_data"]["decision_history"])

    def test_reject_approval_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        response = self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/reject")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_data"]["approval_status"], "rejected")
        self.assertEqual(payload["output"]["approval_status"], "rejected")
        self.assertEqual(payload["span_data"]["decision_action"], "rejected")

    def test_reject_approval_span_appends_chat_event_for_chat_trace(self) -> None:
        session_response = self.client.post(
            "/chat/sessions",
            json={"customer_email": "annual@example.com", "title": "Billing support"},
        )
        session = session_response.json()
        message_response = self.client.post(
            f"/chat/sessions/{session['session_id']}/messages",
            json={"content": "Can you refund my annual plan?"},
        )
        trace = message_response.json()["trace"]
        approval_span = next(span for span in trace["spans"] if span["span_type"] == "approval")

        response = self.client.post(f"/traces/{trace['trace_id']}/approvals/{approval_span['span_id']}/reject")
        messages = self.client.get(f"/chat/sessions/{session['session_id']}/messages").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertIn("rejected", messages[-1]["content"])
        self.assertEqual(messages[-1]["trace_id"], trace["trace_id"])
        self.assertEqual(messages[-1]["metadata"]["event_type"], "approval_decision")
        self.assertEqual(messages[-1]["metadata"]["approval_status"], "rejected")

    def test_revert_approval_span(self) -> None:
        trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))
        self.store.save_trace(trace)

        self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/approve")
        response = self.client.post(f"/traces/{trace.trace_id}/approvals/span_approval_failure/revert")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["span_data"]["approval_status"], "blocked")
        self.assertEqual(payload["output"]["approval_status"], "blocked")
        self.assertIsNone(payload["span_data"]["approved_by"])
        self.assertIsNone(payload["span_data"]["approved_at"])
        self.assertEqual(payload["span_data"]["decision_action"], "reverted")
        self.assertEqual(payload["span_data"]["decision_actor"]["display_name"], "Admin")
        self.assertEqual(
            [event["decision_action"] for event in payload["span_data"]["decision_history"]],
            ["approved", "reverted"],
        )
        saved = self.client.get(f"/traces/{trace.trace_id}").json()
        saved_span = next(span for span in saved["spans"] if span["span_id"] == "span_approval_failure")
        self.assertEqual(
            [event["decision_action"] for event in saved_span["span_data"]["decision_history"]],
            ["approved", "reverted"],
        )

    def test_approval_action_rejects_non_approval_span(self) -> None:
        response = self.client.post(f"/traces/{self.trace.trace_id}/approvals/span_triage/approve")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Span is not an approval gate: span_triage")
