import unittest
from unittest.mock import patch

from agenttrace.agents.support_triage import (
    LLMResponse,
    LocalSupportToolsClient,
    McpSupportToolsClient,
    OpenAIChatCompletionsClient,
    OpenAIResponsesClient,
    StaticLLMClient,
    SupportTriageRunner,
    SupportToolsClient,
    build_default_runner,
)


class FailingLookupTools(SupportToolsClient):
    def lookup_customer(self, email: str) -> dict:
        raise TimeoutError("mcp lookup timed out")

    def retrieve_policy(self, topic: str) -> dict:
        return {"found": False, "topic": topic}

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict:
        return {"status": "not_created"}


class RecordingLLMClient(StaticLLMClient):
    def __init__(self) -> None:
        super().__init__("We found the duplicate charge and created a refund review.")
        self.calls: list[dict] = []

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        return LLMResponse(
            output_text="We found the duplicate charge and created a refund review.",
            input_tokens=42,
            output_tokens=17,
            estimated_cost=0.0003,
            raw_response={"id": "resp_test"},
        )


class QueueLLMClient(StaticLLMClient):
    def __init__(self, outputs: list[str]) -> None:
        super().__init__()
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        output = self.outputs.pop(0)
        return LLMResponse(
            output_text=output,
            input_tokens=11,
            output_tokens=7,
            estimated_cost=0.0001,
            raw_response={"output": output},
        )


class SupportTriageAgentsTest(unittest.TestCase):
    def test_runner_emits_multi_agent_trace_with_llm_generation(self) -> None:
        llm = RecordingLLMClient()
        runner = SupportTriageRunner(llm_client=llm)

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_happy",
        )

        self.assertEqual(trace.trace_id, "trace_runner_happy")
        self.assertEqual(trace.workflow_name, "support-triage")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(trace.metadata["source_kind"], "agent_runner")
        self.assertEqual(trace.metadata["llm_provider"], "static")
        self.assertEqual(trace.metadata["agent_decision_mode"], "deterministic")
        self.assertEqual(
            [span.name for span in trace.spans],
            [
                "Supervisor Agent",
                "Supervisor -> Triage Agent",
                "Triage Agent",
                "Write Working Memory",
                "lookup_customer",
                "Supervisor -> Policy Agent",
                "Policy Agent",
                "retrieve_policy",
                "Read Customer Memory",
                "Action Agent",
                "create_support_action",
                "Validator Agent",
                "Customer Response Generator",
            ],
        )
        self.assertTrue(any(span.span_type == "handoff" for span in trace.spans))
        self.assertTrue(any(span.span_type == "function_tool" for span in trace.spans))
        self.assertTrue(any(span.span_type == "memory_write" for span in trace.spans))
        self.assertTrue(any(span.span_type == "memory_read" for span in trace.spans))
        self.assertTrue(any(span.span_type == "generation" for span in trace.spans))
        self.assertEqual(llm.calls[0]["input_text"].count("duplicate_charge_detected"), 1)

    def test_runner_can_use_llm_backed_specialist_agent_decisions(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"billing request needs triage"}',
                '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"duplicate_charge_refund","reason":"duplicate charge policy applies"}',
                '{"action_type":"refund_review","reason":"Verified duplicate charge and policy allows refund review."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_refund_duplicate_charge"]}',
                "I found the duplicate charge and created a refund review.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_llm_agents",
        )

        self.assertEqual(trace.status, "passed")
        self.assertEqual(trace.metadata["agent_decision_mode"], "llm")
        self.assertEqual(len(llm.calls), 6)
        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        policy = next(span for span in trace.spans if span.name == "Policy Agent")
        action = next(span for span in trace.spans if span.name == "Action Agent")
        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        self.assertEqual(triage.output["issue_type"], "billing_duplicate_charge")
        self.assertEqual(policy.output["retrieval_query"], "duplicate_charge_refund")
        self.assertEqual(action.output["action_type"], "refund_review")
        self.assertEqual(validator.output["grounding_status"], "grounded")
        self.assertEqual(triage.span_data["decision_source"], "llm")
        self.assertEqual(triage.span_data["prompt_version"], "support-triage-v1")
        self.assertEqual(action.input_tokens, 11)

    def test_llm_agent_decisions_fall_back_when_json_is_invalid(self) -> None:
        llm = QueueLLMClient(
            [
                "not json",
                "not json",
                "not json",
                "not json",
                "not json",
                "Fallback customer response.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Can you refund my annual plan?",
            customer_email="annual@example.com",
            trace_id="trace_runner_llm_fallback",
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        action = next(span for span in trace.spans if span.name == "Action Agent")
        self.assertEqual(trace.status, "recovered")
        self.assertEqual(triage.output["issue_type"], "annual_plan_refund")
        self.assertEqual(action.output["action_type"], "refund_review")
        self.assertEqual(triage.span_data["decision_source"], "fallback")
        self.assertEqual(triage.span_data["fallback_reason"], "invalid_json")

    def test_runner_can_emit_spans_incrementally(self) -> None:
        emitted_names: list[str] = []
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_incremental",
            on_span=lambda span: emitted_names.append(span.name),
        )

        self.assertEqual(emitted_names, [span.name for span in trace.spans])
        self.assertEqual(emitted_names[0], "Supervisor Agent")
        self.assertEqual(emitted_names[-1], "Customer Response Generator")

    def test_runner_records_memory_metadata(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="Can you refund my annual plan?",
            customer_email="annual@example.com",
            trace_id="trace_runner_memory",
        )

        memory_spans = [span for span in trace.spans if span.span_type in {"memory_read", "memory_write"}]
        self.assertEqual([span.span_type for span in memory_spans], ["memory_write", "memory_read"])
        self.assertEqual(memory_spans[0].span_data["memory_type"], "short_term")
        self.assertEqual(memory_spans[1].span_data["memory_type"], "long_term")
        self.assertEqual(memory_spans[1].span_data["retrieved_memory_count"], 1)
        self.assertGreater(memory_spans[1].span_data["memory_relevance_score"], 0.8)
        self.assertTrue(memory_spans[1].span_data["memory_used_in_response"])

    def test_runner_records_ignored_stale_memory_for_unverified_customer(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="Can you help with my account?",
            customer_email="unknown@example.com",
            trace_id="trace_runner_memory_warning",
        )

        memory_read = next(span for span in trace.spans if span.span_type == "memory_read")
        self.assertEqual(memory_read.span_data["memory_relevance_score"], 0.42)
        self.assertGreater(memory_read.span_data["memory_age_seconds"], 86400 * 90)
        self.assertFalse(memory_read.span_data["memory_used_in_response"])

    def test_runner_creates_pending_approval_for_high_value_policy(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="Can you refund my annual plan?",
            customer_email="annual@example.com",
            trace_id="trace_runner_approval",
        )

        approval_spans = [span for span in trace.spans if span.span_type == "approval"]
        self.assertEqual(trace.status, "recovered")
        self.assertEqual(len(approval_spans), 1)
        self.assertEqual(approval_spans[0].span_data["approval_status"], "blocked")
        self.assertTrue(approval_spans[0].span_data["approval_required"])

    def test_runner_records_tool_failure(self) -> None:
        runner = SupportTriageRunner(tools_client=FailingLookupTools())

        trace = runner.run(
            message="I cannot access my account after upgrading.",
            customer_email="timeout@example.com",
            trace_id="trace_runner_tool_failure",
        )

        self.assertEqual(trace.status, "failed")
        errored_spans = [span for span in trace.spans if span.error]
        self.assertEqual(len(errored_spans), 1)
        self.assertEqual(errored_spans[0].name, "lookup_customer")
        self.assertEqual(errored_spans[0].span_data["tool_protocol"], "mcp")

    def test_openai_chat_completions_client_uses_generic_openai_protocol(self) -> None:
        calls: list[dict] = []

        def post_json(url: str, *, headers: dict, json: dict, timeout: float) -> dict:
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return {
                "choices": [{"message": {"content": "Your refund review has been created."}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25},
            }

        client = OpenAIChatCompletionsClient(
            api_key="test-key",
            model="gpt-test",
            base_url="http://llm.test/v1",
            post_json=post_json,
        )

        response = client.generate(instructions="Follow policy.", input_text="Customer context.")

        self.assertEqual(response.output_text, "Your refund review has been created.")
        self.assertEqual(response.input_tokens, 100)
        self.assertEqual(response.output_tokens, 25)
        self.assertEqual(calls[0]["url"], "http://llm.test/v1/chat/completions")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(calls[0]["json"]["model"], "gpt-test")
        self.assertEqual(
            calls[0]["json"]["messages"],
            [
                {"role": "system", "content": "Follow policy."},
                {"role": "user", "content": "Customer context."},
            ],
        )

    def test_default_openai_runner_uses_chat_completions_for_generic_compatibility(self) -> None:
        runner = build_default_runner(use_openai=True)

        self.assertIsInstance(runner.llm_client, OpenAIChatCompletionsClient)
        self.assertTrue(runner.use_llm_agents)

    def test_default_openai_runner_can_select_responses_api(self) -> None:
        runner = build_default_runner(use_openai=True, openai_api="responses")

        self.assertIsInstance(runner.llm_client, OpenAIResponsesClient)
        self.assertTrue(runner.use_llm_agents)

    def test_mcp_support_tools_client_calls_expected_tool_names(self) -> None:
        calls: list[dict] = []

        async def call_tool(tool_name: str, arguments: dict) -> dict:
            calls.append({"tool_name": tool_name, "arguments": arguments})
            if tool_name == "lookup_customer_tool":
                return {"found": True, "customer_id": "cus_test"}
            if tool_name == "retrieve_policy_tool":
                return {"found": True, "policy_id": "policy_test"}
            return {"action_id": "act_test", "status": "created"}

        client = McpSupportToolsClient(server_url="http://mcp.test/mcp/", call_tool=call_tool)

        self.assertEqual(client.lookup_customer("customer@example.com")["customer_id"], "cus_test")
        self.assertEqual(client.retrieve_policy("duplicate_charge_refund")["policy_id"], "policy_test")
        self.assertEqual(
            client.create_support_action("cus_test", "refund_review", "reason")["action_id"],
            "act_test",
        )
        self.assertEqual(
            calls,
            [
                {"tool_name": "lookup_customer_tool", "arguments": {"email": "customer@example.com"}},
                {"tool_name": "retrieve_policy_tool", "arguments": {"topic": "duplicate_charge_refund"}},
                {
                    "tool_name": "create_support_action_tool",
                    "arguments": {
                        "customer_id": "cus_test",
                        "action_type": "refund_review",
                        "reason": "reason",
                    },
                },
            ],
        )

    def test_default_runner_uses_mcp_tools_when_url_is_configured(self) -> None:
        with patch.dict("os.environ", {"AGENTTRACE_MCP_TOOLS_URL": "http://mcp.test/mcp/"}):
            runner = build_default_runner()

        self.assertIsInstance(runner.tools_client, McpSupportToolsClient)

    def test_default_runner_uses_local_tools_without_mcp_url(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            runner = build_default_runner()

        self.assertIsInstance(runner.tools_client, LocalSupportToolsClient)


if __name__ == "__main__":
    unittest.main()
