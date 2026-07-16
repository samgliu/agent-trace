import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agenttrace.core.importer import load_trace_file
from agenttrace.core.models import Span, Trace, parse_datetime
from agenttrace.storage.sqlite import SQLiteTraceStore


class SQLiteTraceStoreTest(unittest.TestCase):
    def test_save_and_get_trace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

            store.save_trace(trace)
            saved = store.get_trace(trace.trace_id)

            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.trace_id, trace.trace_id)
            self.assertEqual(saved.workflow_name, "support-triage")
            self.assertEqual(len(saved.spans), len(trace.spans))
            timeline = saved.format_timeline()
            self.assertGreaterEqual(timeline.count("Supervisor Agent"), 1)
            self.assertIn("Estimated cost: $0.0034", timeline)
            self.assertIn("Tokens: input=1550, output=316", timeline)
            self.assertIn("mcp:support-tools-mcp", timeline)
            self.assertNotIn("at 2026-05-01T23:00:00.000Z", timeline)

            verbose_timeline = saved.format_timeline(verbose=True)
            self.assertIn("at 2026-05-01T23:00:00.000Z", verbose_timeline)
            self.assertEqual(saved.raw_payload["trace_id"], trace.trace_id)

    def test_openai_raw_payload_round_trips(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(
                Path("examples/openai_agents/sample_trace_export.json"),
                trace_format="openai-agents",
            )

            store.save_trace(trace)
            saved = store.get_trace(trace.trace_id)

            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.raw_payload["id"], "oa_trace_support_triage_export")
            self.assertEqual(saved.raw_payload["spans"][1]["type"], "model_call")

    def test_list_trace_summaries_filters_by_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            agenttrace_trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))
            openai_trace = load_trace_file(
                Path("examples/openai_agents/sample_trace_export.json"),
                trace_format="openai-agents",
            )

            store.save_trace(agenttrace_trace)
            store.save_trace(openai_trace)
            result = store.list_trace_summaries(source_format="openai-agents", source_kind="trace_export")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["trace_id"], openai_trace.trace_id)
            self.assertEqual(result["items"][0]["source_format"], "openai-agents")
            self.assertEqual(result["items"][0]["source_kind"], "trace_export")
            self.assertIsNotNone(result["items"][0]["ingested_at"])

    def test_list_trace_summaries_includes_error_count(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace_tool_failure.json"))

            store.save_trace(trace)
            result = store.list_trace_summaries(status="failed")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["error_count"], 1)

    def test_list_trace_summaries_filters_by_errors(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            clean_trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))
            errored_trace = load_trace_file(Path("examples/support_triage/sample_trace_tool_failure.json"))

            store.save_trace(clean_trace)
            store.save_trace(errored_trace)
            with_errors = store.list_trace_summaries(has_errors=True)
            without_errors = store.list_trace_summaries(has_errors=False)

            self.assertEqual(with_errors["total"], 1)
            self.assertEqual(with_errors["items"][0]["trace_id"], errored_trace.trace_id)
            self.assertEqual(without_errors["total"], 1)
            self.assertEqual(without_errors["items"][0]["trace_id"], clean_trace.trace_id)

    def test_list_traces(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace.json"))

            store.save_trace(trace)
            traces = store.list_traces()

            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0].trace_id, trace.trace_id)

    def test_list_trace_summaries_filters_by_pending_approval(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            happy_path = load_trace_file(Path("examples/support_triage/sample_trace.json"))
            intervention = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

            store.save_trace(happy_path)
            store.save_trace(intervention)
            result = store.list_trace_summaries(approval_status="pending")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["trace_id"], intervention.trace_id)
            self.assertEqual(result["items"][0]["approval_pending_count"], 1)
            self.assertEqual(result["items"][0]["status"], "passed")
            self.assertEqual(result["items"][0]["grounding_status"], "recovered")

    def test_list_trace_summaries_filters_by_workflow_status_and_date(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            happy_path = load_trace_file(Path("examples/support_triage/sample_trace.json"))
            intervention = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

            store.save_trace(happy_path)
            store.save_trace(intervention)
            result = store.list_trace_summaries(
                workflow_name="support-triage",
                status="passed",
                started_after="2026-05-01T00:00:00Z",
            )

            self.assertEqual(result["total"], 2)

    def test_approval_update_refreshes_trace_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = load_trace_file(Path("examples/support_triage/sample_trace_grounding_failure.json"))

            store.save_trace(trace)
            span = store.get_span(trace.trace_id, "span_approval_failure")
            assert span is not None
            span_data = dict(span.span_data)
            span_data["approval_status"] = "approved"
            store.update_span_payload(trace.trace_id, span.span_id, output={}, span_data=span_data)

            pending = store.list_trace_summaries(approval_status="pending")
            approved = store.list_trace_summaries(approval_status="approved")
            self.assertEqual(pending["total"], 0)
            self.assertEqual(approved["total"], 1)

    def test_upsert_span_updates_running_trace_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = Trace(
                trace_id="live_trace",
                workflow_name="support-triage",
                status="running",
                started_at=parse_datetime("2026-05-03T21:00:00Z"),
            )

            store.upsert_trace(trace)
            saved_span = store.upsert_span(
                Span(
                    span_id="span_live_supervisor",
                    trace_id=trace.trace_id,
                    name="Supervisor Agent",
                    span_type="agent",
                    started_at=parse_datetime("2026-05-03T21:00:00Z"),
                    ended_at=parse_datetime("2026-05-03T21:00:01Z"),
                    input_tokens=10,
                    output_tokens=5,
                    estimated_cost=0.0001,
                )
            )

            self.assertEqual(saved_span.span_id, "span_live_supervisor")
            result = store.list_trace_summaries(status="running")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["span_count"], 1)
            self.assertEqual(result["items"][0]["input_tokens"], 10)

    def test_update_trace_lifecycle_marks_running_trace_passed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = Trace(
                trace_id="live_trace",
                workflow_name="support-triage",
                status="running",
                started_at=parse_datetime("2026-05-03T21:00:00Z"),
            )

            store.upsert_trace(trace)
            updated = store.update_trace_lifecycle(
                trace.trace_id,
                status="passed",
                ended_at="2026-05-03T21:00:04Z",
            )

            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.status, "passed")
            self.assertEqual(updated.duration_ms, 4000)

    def test_chat_session_and_messages_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()

            session = store.create_chat_session(
                customer_email="customer@example.com",
                title="Billing issue",
                metadata={"channel": "demo"},
            )
            user_message = store.add_chat_message(
                session["session_id"],
                role="user",
                content="I was charged twice.",
                trace_id="trace_chat_turn",
            )
            assistant_message = store.add_chat_message(
                session["session_id"],
                role="assistant",
                content="I created a refund review.",
                trace_id="trace_chat_turn",
            )

            saved_session = store.get_chat_session(session["session_id"])
            messages = store.list_chat_messages(session["session_id"])

            self.assertIsNotNone(saved_session)
            assert saved_session is not None
            self.assertEqual(saved_session["customer_email"], "customer@example.com")
            self.assertEqual(saved_session["metadata"]["channel"], "demo")
            self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
            self.assertEqual(messages[0]["message_id"], user_message["message_id"])
            self.assertEqual(messages[1]["message_id"], assistant_message["message_id"])
            self.assertEqual(messages[1]["trace_id"], "trace_chat_turn")

    def test_chat_message_can_be_updated_for_async_completion(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()

            session = store.create_chat_session(customer_email="customer@example.com")
            message = store.add_chat_message(
                session["session_id"],
                role="assistant",
                content="Checking account, policy, and approval context",
                metadata={"status": "pending", "pending": True},
            )

            updated = store.update_chat_message(
                message["message_id"],
                content="I created a refund review.",
                trace_id="trace_chat_turn",
                metadata={"status": "complete", "pending": False},
            )
            messages = store.list_chat_messages(session["session_id"])

            self.assertEqual(updated["content"], "I created a refund review.")
            self.assertEqual(updated["trace_id"], "trace_chat_turn")
            self.assertEqual(updated["metadata"]["status"], "complete")
            self.assertEqual(messages[0]["content"], "I created a refund review.")

    def test_workflow_run_round_trip_and_update(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()

            run = store.create_workflow_run(
                run_id="run_1",
                workflow_name="support-triage",
                trace_id="trace_run_1",
                input_data={
                    "message": "Refund?",
                    "customer_email": "customer@example.com",
                    "use_openai": False,
                    "openai_api": "chat_completions",
                },
            )
            updated = store.update_workflow_run(
                "run_1",
                status="cancel_requested",
                cancel_requested=True,
            )

            reopened = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            reopened.initialize()
            saved = reopened.get_workflow_run("run_1")
            active_runs = reopened.list_active_workflow_runs()

            self.assertEqual(run["status"], "pending")
            self.assertIsNotNone(updated)
            assert saved is not None
            self.assertEqual(saved["run_id"], "run_1")
            self.assertEqual(saved["status"], "cancel_requested")
            self.assertTrue(saved["cancel_requested"])
            self.assertEqual(saved["input"]["customer_email"], "customer@example.com")
            self.assertEqual([item["run_id"] for item in active_runs], ["run_1"])

    def test_eval_run_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            store.save_trace(Trace(trace_id="trace_eval_case", workflow_name="support-triage", status="passed"))

            saved = store.save_eval_run(
                {
                    "suite_id": "support-triage-core",
                    "name": "Support triage core",
                    "execution_mode": "llm",
                    "model_provider": "gemini",
                    "model_name": "gemini-test",
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "pass_rate": 1.0,
                    "results": [
                        {
                            "case_id": "duplicate-charge-refund",
                            "name": "Duplicate charge refund",
                            "trace_id": "trace_eval_case",
                            "passed": True,
                            "score": 1.0,
                            "checks": [
                                {
                                    "name": "trace_status",
                                    "expected": "passed",
                                    "actual": "passed",
                                    "passed": True,
                                }
                            ],
                            "model_events": [
                                {
                                    "agent": "Action Agent",
                                    "model": "gemini-test",
                                    "attempts": [{"model": "gemini-test", "error": "HTTP 429"}],
                                }
                            ],
                        }
                    ],
                },
                run_id="eval_1",
            )

            reopened = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            reopened.initialize()
            listed = reopened.list_eval_runs()
            detail = reopened.get_eval_run("eval_1")

            self.assertEqual(saved["status"], "passed")
            self.assertEqual(saved["execution_mode"], "llm")
            self.assertEqual(saved["model_provider"], "gemini")
            self.assertEqual(listed["total"], 1)
            self.assertEqual(listed["items"][0]["run_id"], "eval_1")
            self.assertEqual(listed["items"][0]["execution_mode"], "llm")
            assert detail is not None
            self.assertEqual(detail["model_name"], "gemini-test")
            self.assertEqual(detail["results"][0]["case_id"], "duplicate-charge-refund")
            self.assertEqual(detail["results"][0]["checks"][0]["name"], "trace_status")
            self.assertEqual(detail["results"][0]["model_events"][0]["agent"], "Action Agent")
            self.assertEqual(detail["results"][0]["model_events"][0]["attempts"][0]["error"], "HTTP 429")

    def test_get_latest_eval_run_filters_by_suite_and_mode(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            for trace_id in ("trace_eval_old", "trace_eval_new"):
                store.save_trace(Trace(trace_id=trace_id, workflow_name="support-triage", status="passed"))

            def payload(trace_id: str, mode: str) -> dict[str, object]:
                return {
                    "suite_id": "support-triage-core",
                    "name": "Support triage core",
                    "execution_mode": mode,
                    "model_provider": "static" if mode == "deterministic" else "gemini",
                    "model_name": "deterministic" if mode == "deterministic" else "gemini-test",
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "pass_rate": 1.0,
                    "results": [
                        {
                            "case_id": "case",
                            "name": "Case",
                            "trace_id": trace_id,
                            "passed": True,
                            "score": 1.0,
                            "checks": [],
                        }
                    ],
                }

            with patch(
                "agenttrace.storage.sqlite._utc_now",
                side_effect=["2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z"],
            ):
                store.save_eval_run(payload("trace_eval_old", "llm"), run_id="eval_old")
                store.save_eval_run(payload("trace_eval_new", "llm"), run_id="eval_new")

            latest = store.get_latest_eval_run(suite_id="support-triage-core", execution_mode="llm")

            assert latest is not None
            self.assertEqual(latest["run_id"], "eval_new")
            self.assertIsNone(store.get_latest_eval_run(suite_id="support-triage-core", execution_mode="deterministic"))

    def test_trace_summary_includes_chat_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            trace = Trace(
                trace_id="trace_chat_turn",
                workflow_name="support-triage",
                status="passed",
                metadata={
                    "source_format": "agenttrace",
                    "source_kind": "agent_runner",
                    "chat_session_id": "chat_123",
                    "chat_user_message_id": "msg_123",
                },
            )

            store.save_trace(trace)
            result = store.list_trace_summaries()

            self.assertEqual(result["items"][0]["metadata"]["chat_session_id"], "chat_123")
            self.assertEqual(result["items"][0]["metadata"]["chat_user_message_id"], "msg_123")

    def test_list_trace_summaries_filters_by_chat_session(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            store.save_trace(
                Trace(
                    trace_id="trace_chat_1",
                    workflow_name="support-triage",
                    status="passed",
                    metadata={"chat_session_id": "chat_1"},
                )
            )
            store.save_trace(
                Trace(
                    trace_id="trace_chat_2",
                    workflow_name="support-triage",
                    status="passed",
                    metadata={"chat_session_id": "chat_2"},
                )
            )

            result = store.list_trace_summaries(chat_session_id="chat_1")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["trace_id"], "trace_chat_1")

    def test_trace_summaries_by_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTraceStore(Path(temp_dir) / "agenttrace.db")
            store.initialize()
            store.save_trace(Trace(trace_id="trace_1", workflow_name="support-triage", status="passed"))
            store.save_trace(Trace(trace_id="trace_2", workflow_name="support-triage", status="failed"))

            result = store.trace_summaries_by_ids(["trace_2", "missing", "trace_2", "trace_1"])

            self.assertEqual({item["trace_id"] for item in result}, {"trace_1", "trace_2"})
