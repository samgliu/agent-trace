import os
import unittest
from unittest.mock import patch

from agent_apps.customer_service.runner import (
    LLMResponse,
    LocalSupportToolsClient,
    McpSupportToolsClient,
    OpenAIChatCompletionsClient,
    OpenAIResponsesClient,
    StaticLLMClient,
    SupportTriageRunner,
    SupportToolsClient,
    _provider_http_error_message,
    build_default_runner,
    resolve_model_config,
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
                "Update Agent State",
                "create_refund_review",
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
        self.assertEqual(triage.span_data["model_provider"], "static")
        self.assertEqual(
            triage.span_data["model_output_text"],
            '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
        )
        self.assertEqual(action.input_tokens, 11)

    def test_supervisor_can_route_clarification_directly_to_response(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"clarify_request","handoff_reason":"The customer has not stated a support issue yet."}',
                "I can help with orders, billing, subscriptions, or account access. What do you need help with?",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Hello, what can you help me with?",
            customer_email="customer@example.com",
            trace_id="trace_runner_clarify_route",
        )

        supervisor = next(span for span in trace.spans if span.name == "Supervisor Agent")
        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(trace.metadata["supervisor_route"], "clarify_request")
        self.assertEqual(supervisor.output["route"], "clarify_request")
        self.assertEqual(supervisor.span_data["supervisor_route"], "clarify_request")
        self.assertEqual(
            [span.name for span in trace.spans],
            ["Supervisor Agent", "Supervisor -> Customer Response Generator", "Customer Response Generator"],
        )
        self.assertEqual(response.span_data["supervisor_route"], "clarify_request")
        self.assertEqual(len(llm.calls), 2)

    def test_supervisor_cannot_skip_support_flow_for_actionable_request(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"clarify_request","handoff_reason":"Ask what the customer needs."}',
                '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"duplicate_charge_refund","reason":"duplicate charge policy applies"}',
                '{"action_type":"refund_review","reason":"Verified duplicate charge."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_refund_duplicate_charge"]}',
                "I found the duplicate charge and created a refund review.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_invalid_clarify_route",
        )

        supervisor = next(span for span in trace.spans if span.name == "Supervisor Agent")
        self.assertEqual(trace.metadata["supervisor_route"], "standard_support")
        self.assertEqual(supervisor.output["route"], "standard_support")
        self.assertEqual(supervisor.span_data["decision_source"], "policy_validation")
        self.assertEqual(supervisor.span_data["validation_reason"], "actionable_request_requires_support_route")
        self.assertIn("Triage Agent", [span.name for span in trace.spans])
        self.assertIn("create_refund_review", [span.name for span in trace.spans])

    def test_llm_agent_action_falls_back_when_action_type_is_unsupported(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"billing request needs triage"}',
                '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"duplicate_charge_refund","reason":"duplicate charge policy applies"}',
                '{"action_type":"wire_money","reason":"Unsupported action selected by model."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_refund_duplicate_charge"]}',
                "I found the duplicate charge and created a refund review.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_invalid_action",
        )

        action = next(span for span in trace.spans if span.name == "Action Agent")
        create_action = next(span for span in trace.spans if span.name == "create_refund_review")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(action.output["action_type"], "refund_review")
        self.assertEqual(action.span_data["decision_source"], "policy_validation")
        self.assertEqual(action.span_data["validation_reason"], "unsupported_action_type")
        self.assertEqual(action.span_data["rejected_action_type"], "wire_money")
        self.assertEqual(
            action.span_data["model_output_text"],
            '{"action_type":"wire_money","reason":"Unsupported action selected by model."}',
        )
        self.assertEqual(create_action.output["status"], "created")

    def test_llm_agent_action_enforces_refund_review_path(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"billing request needs triage"}',
                '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"duplicate_charge_refund","reason":"duplicate charge policy applies"}',
                '{"action_type":"instant_refund","reason":"Refund immediately."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_refund_duplicate_charge"]}',
                "I issued an instant refund.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_refund_review_enforced",
        )

        action = next(span for span in trace.spans if span.name == "Action Agent")
        create_action = next(span for span in trace.spans if span.name == "create_refund_review")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(action.output["action_type"], "refund_review")
        self.assertEqual(action.span_data["validation_reason"], "refund_review_required_by_policy_path")
        self.assertEqual(action.span_data["rejected_action_type"], "instant_refund")
        self.assertEqual(create_action.span_data["tool_name"], "create_refund_review_tool")

    def test_llm_agent_action_enforces_approval_ready_refund_review(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"annual refund needs triage"}',
                '{"issue_type":"annual_plan_refund","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"annual_plan_refund","reason":"annual refund policy applies"}',
                '{"action_type":"clarification_request","reason":"Ask for more details."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_annual_800"]}',
                "I created a refund review pending approval.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Can you refund my annual plan?",
            customer_email="annual@example.com",
            trace_id="trace_runner_annual_refund_review_enforced",
        )

        action = next(span for span in trace.spans if span.name == "Action Agent")
        state_update = next(span for span in trace.spans if span.name == "Update Agent State")
        self.assertEqual(trace.status, "recovered")
        self.assertEqual(action.output["action_type"], "refund_review")
        self.assertEqual(action.span_data["validation_reason"], "refund_review_required_by_policy_path")
        self.assertEqual(state_update.output["agent_state"]["next_required_step"], "human_approval")

    def test_llm_triage_rejects_recent_context_as_issue_type(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"account request needs triage"}',
                '{"issue_type":"recent_context","urgency":"low","sentiment":"concerned"}',
                '{"retrieval_query":"recent_context","reason":"Use recent context"}',
                '{"action_type":"clarification_request","reason":"Need details."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123"]}',
                "Could you share more detail?",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Can you help with my account?",
            customer_email="unknown@example.com",
            trace_id="trace_runner_recent_context_rejected",
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        policy = next(span for span in trace.spans if span.name == "Policy Agent")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(triage.output["issue_type"], "general_support")
        self.assertEqual(triage.span_data["validation_reason"], "unsupported_issue_type")
        self.assertEqual(policy.output["retrieval_query"], "general_support")

    def test_llm_action_enforces_consumed_product_quality_exception(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"product issue needs triage"}',
                '{"issue_type":"consumed_product_return","urgency":"low","sentiment":"concerned"}',
                '{"retrieval_query":"consumed_product_return","reason":"consumed product policy applies"}',
                '{"action_type":"clarification_request","reason":"Ask for more details."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","ord_1234","policy_consumed_product_return"]}',
                "I submitted this for quality review.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Order number #1234. The bananas were moldy and unsafe, so I threw them out.",
            customer_email="customer@example.com",
            trace_id="trace_runner_quality_exception_action_enforced",
            conversation_history=[
                {
                    "role": "user",
                    "content": "I'd like to return the banana I bought last week. I ate all of them already.",
                },
                {
                    "role": "assistant",
                    "content": "Please share the order number or receipt and what was wrong.",
                },
            ],
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        action = next(span for span in trace.spans if span.name == "Action Agent")
        create_action = next(span for span in trace.spans if span.name == "create_quality_exception_review")
        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertEqual(trace.status, "passed")
        self.assertTrue(triage.output["quality_exception"])
        self.assertEqual(action.output["action_type"], "courtesy_credit")
        self.assertEqual(action.span_data["validation_reason"], "quality_exception_action_required")
        self.assertEqual(create_action.span_data["tool_name"], "create_quality_exception_review_tool")
        self.assertIn("courtesy credit", response.output["response"].lower())

    def test_llm_action_enforces_general_support_clarification(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"account ownership request needs triage"}',
                '{"issue_type":"general_support","urgency":"medium","sentiment":"concerned","missing_information":"verified account or matching order ownership"}',
                '{"retrieval_query":"general_support","reason":"ownership must be verified"}',
                '{"action_type":"escalation","reason":"Escalate ownership mismatch."}',
                '{"grounding_status":"recovered","approval_required":true,"evidence":["account_access_mismatch"]}',
                "Please provide the matching account detail.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="The order is under my spouse's different email. Can you refund it from this account?",
            customer_email="customer@example.com",
            trace_id="trace_runner_general_support_clarification_enforced",
        )

        action = next(span for span in trace.spans if span.name == "Action Agent")
        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        state_update = next(span for span in trace.spans if span.name == "Update Agent State")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(action.output["action_type"], "clarification_request")
        self.assertEqual(action.span_data["validation_reason"], "clarification_required_by_policy_path")
        self.assertFalse(validator.output["approval_required"])
        self.assertEqual(validator.output["grounding_status"], "grounded")
        self.assertEqual(state_update.output["agent_state"]["next_required_step"], "collect_missing_information")

    def test_validator_enforces_policy_required_approval(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"annual refund needs triage"}',
                '{"issue_type":"annual_plan_refund","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"annual_plan_refund","reason":"annual refund policy applies"}',
                '{"action_type":"refund_review","reason":"Review annual refund."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_annual_800"]}',
                "I created a refund review pending approval.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Can you refund my annual plan?",
            customer_email="annual@example.com",
            trace_id="trace_runner_approval_enforced",
        )

        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        approval_spans = [span for span in trace.spans if span.span_type == "approval"]
        self.assertEqual(trace.status, "recovered")
        self.assertTrue(validator.output["approval_required"])
        self.assertEqual(validator.output["grounding_status"], "recovered")
        self.assertEqual(validator.output["validator_corrections"], ["required_approval_enforced"])
        self.assertEqual(len(approval_spans), 1)

    def test_validator_removes_unnecessary_approval_for_clarification(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"account ownership request needs triage"}',
                '{"issue_type":"general_support","urgency":"medium","sentiment":"concerned","missing_information":"verified account or matching order ownership"}',
                '{"retrieval_query":"general_support","reason":"ownership must be verified"}',
                '{"action_type":"clarification_request","reason":"Need matching account details."}',
                '{"grounding_status":"recovered","approval_required":true,"evidence":["account_access_mismatch"]}',
                "Please provide the matching account detail.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="The order is under my spouse's different email. Can you refund it from this account?",
            customer_email="customer@example.com",
            trace_id="trace_runner_unnecessary_approval_removed",
        )

        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        approval_spans = [span for span in trace.spans if span.span_type == "approval"]
        self.assertEqual(trace.status, "passed")
        self.assertFalse(validator.output["approval_required"])
        self.assertEqual(validator.output["grounding_status"], "grounded")
        self.assertIn("unnecessary_approval_removed", validator.output["validator_corrections"])
        self.assertEqual(approval_spans, [])

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
        self.assertEqual(triage.span_data["model_output_text"], "not json")

    def test_validator_records_customer_friendly_grounding_evidence(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_grounding_evidence",
        )

        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        self.assertEqual(validator.output["grounding_status"], "grounded")
        self.assertIn("refund_review", validator.output["allowed_actions"])
        self.assertEqual(
            validator.output["grounding_evidence"],
            [
                {"type": "customer", "id": "cus_123"},
                {"type": "policy", "id": "policy_refund_duplicate_charge"},
                {"type": "action", "id": "rr_cus_123_policy_refund_duplicate_charge"},
            ],
        )
        self.assertIn("Resolve verified duplicate charges", validator.output["customer_friendly_resolution"])

    def test_stale_subscription_refund_does_not_default_to_duplicate_charge(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I want a refund on my Prime subscription that was billed 3 years ago. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_stale_subscription_refund",
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        policy = next(span for span in trace.spans if span.name == "Policy Agent")
        subscription = next(span for span in trace.spans if span.name == "lookup_subscription")
        retrieval = next(span for span in trace.spans if span.name == "retrieve_policy")
        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        self.assertEqual(trace.status, "recovered")
        self.assertEqual(triage.output["issue_type"], "stale_subscription_refund")
        self.assertEqual(policy.output["retrieval_query"], "stale_subscription_refund")
        self.assertEqual(subscription.output["subscription_id"], "sub_cus_123_pro")
        self.assertEqual(subscription.span_data["tool_name"], "lookup_subscription_tool")
        self.assertEqual(retrieval.output["policy_id"], "policy_stale_subscription_refund")
        self.assertTrue(validator.output["approval_required"])
        self.assertIn("sub_cus_123_pro", validator.output["evidence"])
        self.assertEqual(retrieval.output["topic"], "stale_subscription_refund")

    def test_annual_plan_refund_uses_subscription_evidence(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="Can you refund my annual plan?",
            customer_email="annual@example.com",
            trace_id="trace_runner_annual_subscription_evidence",
        )

        subscription = next(span for span in trace.spans if span.name == "lookup_subscription")
        action = next(span for span in trace.spans if span.name == "create_refund_review")
        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        self.assertEqual(subscription.output["subscription_id"], "sub_annual_800")
        self.assertEqual(subscription.output["billing_period"], "annual")
        self.assertEqual(action.output["amount_usd"], 800)
        self.assertIn("sub_annual_800", action.output["evidence_ids"])
        self.assertIn("sub_annual_800", validator.output["evidence"])

    def test_static_customer_response_uses_selected_policy_context(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I want a refund on my Prime subscription that was billed 3 years ago. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_static_response_policy_context",
        )

        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertIn("older subscription charge", response.output["response"])
        self.assertNotIn("duplicate charge", response.output["response"].lower())

    def test_static_customer_response_handles_follow_up_context_naturally(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I still want a refund on that Prime subscription billed 3 years ago. What happens next?",
            customer_email="customer@example.com",
            trace_id="trace_runner_static_response_follow_up",
            conversation_history=[
                {
                    "role": "user",
                    "content": "I want a refund on my Prime subscription that was billed 3 years ago.",
                },
                {
                    "role": "assistant",
                    "content": "I started a refund review for the older subscription charge.",
                },
            ],
        )

        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertIn("follow-up", response.output["response"])
        self.assertIn("older-subscription refund review", response.output["response"])
        self.assertNotIn("I started", response.output["response"])
        self.assertEqual(trace.metadata["conversation_history_count"], 2)

    def test_consumed_product_return_does_not_pivot_to_duplicate_charge(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I'd like to return the banana I bought last week. I ate all of them already.",
            customer_email="customer@example.com",
            trace_id="trace_runner_consumed_product_return",
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        retrieval = next(span for span in trace.spans if span.name == "retrieve_policy")
        action = next(span for span in trace.spans if span.name == "Action Agent")
        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(triage.output["issue_type"], "consumed_product_return")
        self.assertEqual(retrieval.output["policy_id"], "policy_consumed_product_return")
        self.assertEqual(action.output["action_type"], "clarification_request")
        self.assertIn("fully consumed", response.output["response"])
        self.assertNotIn("duplicate", response.output["response"].lower())
        self.assertNotIn("$20", response.output["response"])

    def test_consumed_product_return_follow_up_keeps_active_issue(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="Order number: #1234",
            customer_email="customer@example.com",
            trace_id="trace_runner_consumed_product_return_follow_up",
            conversation_history=[
                {
                    "role": "user",
                    "content": "I'd like to return the banana I bought last week. I ate all of them already.",
                },
                {
                    "role": "assistant",
                    "content": "Please share the order number or receipt and what was wrong.",
                },
            ],
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        retrieval = next(span for span in trace.spans if span.name == "retrieve_policy")
        order = next(span for span in trace.spans if span.name == "lookup_order")
        owner = next(span for span in trace.spans if span.name == "verify_order_owner")
        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertEqual(triage.output["issue_type"], "consumed_product_return")
        self.assertEqual(retrieval.output["policy_id"], "policy_consumed_product_return")
        self.assertEqual(order.output["order_id"], "ord_1234")
        self.assertTrue(owner.output["verified"])
        self.assertIn("order number", response.output["response"].lower())
        self.assertIn("normal return", response.output["response"])
        self.assertNotIn("duplicate", response.output["response"].lower())
        self.assertNotIn("$20", response.output["response"])
        self.assertEqual(trace.metadata["conversation_history_count"], 2)

    def test_llm_response_keeps_consumed_product_policy_terms(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"product issue needs triage"}',
                '{"issue_type":"consumed_product_return","urgency":"low","sentiment":"concerned","quality_exception":true}',
                '{"retrieval_query":"consumed_product_return","reason":"consumed product policy applies"}',
                '{"action_type":"courtesy_credit","reason":"Quality exception can be reviewed."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","ord_1234","policy_consumed_product_return"]}',
                "I can review the quality issue with the order evidence.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="Order number #1234. The bananas were moldy and unsafe, so I threw them out.",
            customer_email="customer@example.com",
            trace_id="trace_runner_consumed_response_guarded",
            conversation_history=[
                {
                    "role": "user",
                    "content": "I'd like to return the banana I bought last week. I ate all of them already.",
                },
                {
                    "role": "assistant",
                    "content": "Please share the order number or receipt and what was wrong.",
                },
            ],
        )

        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertEqual(trace.status, "passed")
        self.assertIn("quality", response.output["response"].lower())
        self.assertIn("courtesy credit", response.output["response"].lower())

    def test_account_mismatch_uses_scoped_verification_tool(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="The order is under my spouse's different email. Can you refund it from this account?",
            customer_email="customer@example.com",
            trace_id="trace_runner_account_mismatch",
        )

        verification = next(span for span in trace.spans if span.name == "verify_account_access")
        action = next(span for span in trace.spans if span.name == "Action Agent")
        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertFalse(verification.output["verified"])
        self.assertEqual(verification.output["reason"], "requested_resource_belongs_to_different_account")
        self.assertEqual(verification.span_data["tool_name"], "verify_account_access_tool")
        self.assertEqual(action.output["action_type"], "clarification_request")
        self.assertIn("account_access_mismatch", validator.output["evidence"])
        self.assertNotIn("refund review", response.output["response"].lower())

    def test_validator_requires_human_review_for_high_abuse_risk_refund(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="risk@example.com",
            trace_id="trace_runner_abuse_risk_review",
        )

        validator = next(span for span in trace.spans if span.name == "Validator Agent")
        self.assertEqual(trace.status, "recovered")
        self.assertTrue(validator.output["approval_required"])
        self.assertTrue(validator.output["risk_review_required"])
        self.assertEqual(validator.output["abuse_risk"]["level"], "high")
        self.assertIn("high_prior_refund_count", validator.output["abuse_risk"]["signals"])
        self.assertIn("abuse_review_enforced", validator.output["validator_corrections"])
        escalation = next(span for span in trace.spans if span.name == "Escalation Agent")
        self.assertEqual(escalation.output["escalation_type"], "risk_review")
        self.assertEqual(escalation.output["next_owner"], "trust_and_safety")
        self.assertIn("policy_refund_duplicate_charge", escalation.output["evidence"])

    def test_explicit_human_request_uses_escalation_agent(self) -> None:
        runner = SupportTriageRunner()

        trace = runner.run(
            message="I want to speak to a human agent about my account.",
            customer_email="customer@example.com",
            trace_id="trace_runner_explicit_escalation",
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        action = next(span for span in trace.spans if span.name == "Action Agent")
        state_update = next(span for span in trace.spans if span.name == "Update Agent State")
        escalation = next(span for span in trace.spans if span.name == "Escalation Agent")
        response = next(span for span in trace.spans if span.name == "Customer Response Generator")
        self.assertEqual(trace.status, "passed")
        self.assertTrue(triage.output["escalation_requested"])
        self.assertEqual(action.output["action_type"], "escalation")
        self.assertEqual(state_update.output["agent_state"]["next_required_step"], "human_review")
        self.assertEqual(escalation.output["escalation_type"], "human_review")
        self.assertEqual(escalation.output["next_owner"], "support_specialist")
        self.assertIn("escalating", response.output["response"].lower())

    def test_llm_action_enforces_explicit_human_escalation(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"customer asked for human help"}',
                '{"issue_type":"general_support","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"general_support","reason":"general support policy applies"}',
                '{"action_type":"clarification_request","reason":"Ask for account details."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_general_support"]}',
                '{"escalation_type":"human_review","reason":"Customer asked for human support.","handoff_summary":"Route to human support with account context.","next_owner":"support_specialist","evidence":["cus_123","policy_general_support"]}',
                "I am escalating this to a human support specialist.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I want to speak to a human agent about my account.",
            customer_email="customer@example.com",
            trace_id="trace_runner_llm_explicit_escalation_enforced",
        )

        action = next(span for span in trace.spans if span.name == "Action Agent")
        escalation = next(span for span in trace.spans if span.name == "Escalation Agent")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(action.output["action_type"], "escalation")
        self.assertEqual(action.span_data["validation_reason"], "escalation_required_by_customer_request")
        self.assertEqual(action.span_data["rejected_action_type"], "clarification_request")
        self.assertEqual(escalation.output["escalation_type"], "human_review")

    def test_llm_triage_is_corrected_when_message_signals_stale_refund(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"billing request needs triage"}',
                '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"duplicate_charge_refund","reason":"customer has a duplicate charge flag"}',
                '{"action_type":"refund_review","reason":"Review stale subscription refund."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123"]}',
                "I started a refund review for the old subscription charge.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I want a refund on my Prime subscription that was billed 3 years ago. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_stale_subscription_llm_correction",
        )

        triage = next(span for span in trace.spans if span.name == "Triage Agent")
        policy = next(span for span in trace.spans if span.name == "Policy Agent")
        retrieval = next(span for span in trace.spans if span.name == "retrieve_policy")
        self.assertEqual(triage.output["issue_type"], "stale_subscription_refund")
        self.assertEqual(triage.span_data["validation_reason"], "message_policy_signal_mismatch")
        self.assertEqual(policy.output["retrieval_query"], "stale_subscription_refund")
        self.assertEqual(policy.span_data["validation_reason"], "policy_topic_mismatch")
        self.assertEqual(retrieval.output["policy_id"], "policy_stale_subscription_refund")

    def test_action_agent_falls_back_when_policy_disallows_action(self) -> None:
        llm = QueueLLMClient(
            [
                '{"route":"triage","handoff_reason":"billing request needs triage"}',
                '{"issue_type":"billing_duplicate_charge","urgency":"medium","sentiment":"concerned"}',
                '{"retrieval_query":"duplicate_charge_refund","reason":"duplicate charge policy applies"}',
                '{"action_type":"cancel_plan","reason":"Canceling would be too aggressive for a duplicate charge."}',
                '{"grounding_status":"grounded","approval_required":false,"evidence":["cus_123","policy_refund_duplicate_charge"]}',
                "I found the duplicate charge and created a refund review.",
            ]
        )
        runner = SupportTriageRunner(llm_client=llm, use_llm_agents=True)

        trace = runner.run(
            message="I was charged twice for my Pro subscription yesterday. Can I get a refund?",
            customer_email="customer@example.com",
            trace_id="trace_runner_policy_disallowed_action",
        )

        action = next(span for span in trace.spans if span.name == "Action Agent")
        self.assertEqual(action.output["action_type"], "refund_review")
        self.assertEqual(action.span_data["decision_source"], "policy_validation")
        self.assertEqual(action.span_data["validation_reason"], "action_not_allowed_by_policy")
        self.assertEqual(action.span_data["rejected_action_type"], "cancel_plan")

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
        self.assertEqual([span.span_type for span in memory_spans], ["memory_write", "memory_read", "memory_write"])
        self.assertEqual(memory_spans[0].span_data["memory_type"], "short_term")
        self.assertEqual(memory_spans[1].span_data["memory_type"], "long_term")
        self.assertEqual(memory_spans[2].span_data["memory_type"], "short_term")
        self.assertEqual(memory_spans[2].output["agent_state"]["next_required_step"], "human_approval")
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
        escalation = next(span for span in trace.spans if span.name == "Escalation Agent")
        self.assertEqual(escalation.output["escalation_type"], "technical_recovery")
        self.assertEqual(escalation.output["next_owner"], "support_operations")

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

    def test_openai_chat_completions_client_wraps_provider_http_errors(self) -> None:
        def post_json(url: str, *, headers: dict, json: dict, timeout: float) -> dict:
            raise RuntimeError("LLM provider request failed with HTTP 429.")

        client = OpenAIChatCompletionsClient(
            api_key="test-key",
            model="gpt-test",
            base_url="http://llm.test/v1",
            post_json=post_json,
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
            client.generate(instructions="Follow policy.", input_text="Customer context.")

    def test_openai_chat_completions_client_falls_back_on_capacity_errors(self) -> None:
        calls: list[str] = []

        def post_json(url: str, *, headers: dict, json: dict, timeout: float) -> dict:
            calls.append(json["model"])
            if json["model"] == "gemini-primary":
                raise RuntimeError("LLM provider request failed with HTTP 503: UNAVAILABLE")
            return {
                "choices": [{"message": {"content": "Fallback model answered."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

        with patch.dict(
            "os.environ",
            {"LLM_PROVIDER": "gemini", "GEMINI_FALLBACK_MODELS": "gemini-fallback"},
            clear=True,
        ):
            client = OpenAIChatCompletionsClient(
                api_key="test-key",
                model="gemini-primary",
                base_url="http://llm.test/v1",
                post_json=post_json,
            )

        response = client.generate(instructions="Follow policy.", input_text="Customer context.")

        self.assertEqual(response.output_text, "Fallback model answered.")
        self.assertEqual(calls, ["gemini-primary", "gemini-fallback"])
        self.assertEqual(response.raw_response["agenttrace_model"], "gemini-fallback")
        self.assertTrue(response.raw_response["agenttrace_model_fallback_used"])
        self.assertEqual(
            response.raw_response["agenttrace_model_attempts"],
            [
                {
                    "model": "gemini-primary",
                    "status": "failed",
                    "error": "LLM provider request failed with HTTP 503: UNAVAILABLE",
                },
                {"model": "gemini-fallback", "status": "succeeded"},
            ],
        )

    def test_openai_chat_completions_client_does_not_fallback_on_non_capacity_errors(self) -> None:
        calls: list[str] = []

        def post_json(url: str, *, headers: dict, json: dict, timeout: float) -> dict:
            calls.append(json["model"])
            raise RuntimeError("LLM provider request failed with HTTP 400.")

        with patch.dict(
            "os.environ",
            {"LLM_PROVIDER": "gemini", "GEMINI_FALLBACK_MODELS": "gemini-fallback"},
            clear=True,
        ):
            client = OpenAIChatCompletionsClient(
                api_key="test-key",
                model="gemini-primary",
                base_url="http://llm.test/v1",
                post_json=post_json,
            )

        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            client.generate(instructions="Follow policy.", input_text="Customer context.")
        self.assertEqual(calls, ["gemini-primary"])

    def test_provider_http_error_message_includes_provider_detail(self) -> None:
        message = _provider_http_error_message(
            429,
            '{"error":{"message":"You exceeded your current quota, please check your plan and billing details.","status":"RESOURCE_EXHAUSTED"}}',
        )

        self.assertIn("HTTP 429", message)
        self.assertIn("exceeded your current quota", message)

    def test_openai_chat_completions_client_reports_missing_provider_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            client = OpenAIChatCompletionsClient(
                api_key=None,
                model="gemini-test",
                base_url="http://llm.test/v1",
            )
        client.provider = "gemini"

        with self.assertRaisesRegex(RuntimeError, "Set GEMINI_API_KEY or LLM_API_KEY"):
            client.generate(instructions="Follow policy.", input_text="Customer context.")

    def test_model_config_uses_provider_specific_credentials(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": "gemini-key",
                "GEMINI_MODEL": "gemini-test",
            },
            clear=True,
        ):
            config = resolve_model_config()

        self.assertEqual(config.provider, "gemini")
        self.assertEqual(config.api_key, "gemini-key")
        self.assertEqual(config.model, "gemini-test")
        self.assertEqual(config.base_url, "https://generativelanguage.googleapis.com/v1beta/openai")

    def test_model_config_uses_provider_specific_fallback_models(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": "gemini-key",
                "GEMINI_MODEL": "gemini-primary",
                "GEMINI_FALLBACK_MODELS": "gemini-fallback-a, gemini-fallback-b",
                "LLM_FALLBACK_MODELS": "generic-fallback",
            },
            clear=True,
        ):
            config = resolve_model_config()

        self.assertEqual(config.model, "gemini-primary")
        self.assertEqual(config.fallback_models, ("gemini-fallback-a", "gemini-fallback-b"))

    def test_model_config_uses_provider_specific_base_url_before_generic_gateway_settings(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "anthropic-key",
                "ANTHROPIC_MODEL": "claude-test",
                "ANTHROPIC_BASE_URL": "http://anthropic-gateway.test/v1",
                "LLM_BASE_URL": "http://generic-gateway.test/v1",
            },
            clear=True,
        ):
            config = resolve_model_config()

        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.api_key, "anthropic-key")
        self.assertEqual(config.model, "claude-test")
        self.assertEqual(config.base_url, "http://anthropic-gateway.test/v1")

    def test_model_config_uses_generic_llm_settings_as_fallback(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "openai-compatible",
                "LLM_API_KEY": "generic-key",
                "LLM_MODEL": "gateway-model",
                "LLM_BASE_URL": "http://gateway.test/v1",
            },
            clear=True,
        ):
            config = resolve_model_config()

        self.assertEqual(config.provider, "openai-compatible")
        self.assertEqual(config.api_key, "generic-key")
        self.assertEqual(config.model, "gateway-model")
        self.assertEqual(config.base_url, "http://gateway.test/v1")

    def test_model_config_keeps_legacy_openai_env_as_fallback(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "legacy-key",
                "AGENTTRACE_OPENAI_MODEL": "legacy-model",
                "AGENTTRACE_OPENAI_BASE_URL": "http://legacy.test/v1",
            },
            clear=True,
        ):
            config = resolve_model_config()

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.api_key, "legacy-key")
        self.assertEqual(config.model, "legacy-model")
        self.assertEqual(config.base_url, "http://legacy.test/v1")

    def test_default_openai_runner_uses_chat_completions_for_generic_compatibility(self) -> None:
        runner = build_default_runner(use_openai=True)

        self.assertIsInstance(runner.llm_client, OpenAIChatCompletionsClient)
        self.assertTrue(runner.use_llm_agents)
        self.assertEqual(runner.llm_client.provider_name, "openai-chat-completions")
        self.assertEqual(runner.llm_client.timeout_seconds, 180.0)

    def test_openai_runner_can_configure_llm_timeout(self) -> None:
        with patch.dict("os.environ", {"AGENTTRACE_LLM_TIMEOUT_SECONDS": "90"}):
            runner = build_default_runner(use_openai=True)

        self.assertIsInstance(runner.llm_client, OpenAIChatCompletionsClient)
        self.assertEqual(runner.llm_client.timeout_seconds, 90.0)

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
            if tool_name == "lookup_order_tool":
                return {"found": True, "order_id": "ord_test"}
            if tool_name == "lookup_charge_tool":
                return {"found": True, "charges": [{"charge_id": "chg_test"}]}
            if tool_name == "lookup_subscription_tool":
                return {"found": True, "subscription_id": "sub_test"}
            if tool_name == "verify_account_access_tool":
                return {"verified": False, "reason": "requested_resource_belongs_to_different_account"}
            if tool_name == "verify_order_owner_tool":
                return {"verified": True, "order_id": "ord_test"}
            return {"action_id": "act_test", "status": "created"}

        client = McpSupportToolsClient(server_url="http://mcp.test/mcp/", call_tool=call_tool)

        self.assertEqual(client.lookup_customer("customer@example.com")["customer_id"], "cus_test")
        self.assertEqual(client.retrieve_policy("duplicate_charge_refund")["policy_id"], "policy_test")
        self.assertEqual(
            client.create_support_action("cus_test", "refund_review", "reason")["action_id"],
            "act_test",
        )
        self.assertEqual(client.lookup_order("#1234")["order_id"], "ord_test")
        self.assertEqual(client.lookup_charge("cus_test")["charges"][0]["charge_id"], "chg_test")
        self.assertEqual(client.lookup_subscription("cus_test")["subscription_id"], "sub_test")
        self.assertFalse(client.verify_account_access("cus_test", "spouse different email")["verified"])
        self.assertTrue(client.verify_order_owner("#1234", "cus_test")["verified"])
        self.assertEqual(
            client.create_refund_review("cus_test", "policy_test", "reason", 20, ["cus_test"])["action_id"],
            "act_test",
        )
        self.assertEqual(
            client.create_quality_exception_review("cus_test", "ord_test", "reason", ["ord_test"])["action_id"],
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
                {"tool_name": "lookup_order_tool", "arguments": {"order_number": "#1234"}},
                {"tool_name": "lookup_charge_tool", "arguments": {"customer_id": "cus_test", "charge_id": None}},
                {"tool_name": "lookup_subscription_tool", "arguments": {"customer_id": "cus_test"}},
                {
                    "tool_name": "verify_account_access_tool",
                    "arguments": {
                        "customer_id": "cus_test",
                        "requested_account_hint": "spouse different email",
                    },
                },
                {
                    "tool_name": "verify_order_owner_tool",
                    "arguments": {"order_number": "#1234", "customer_id": "cus_test"},
                },
                {
                    "tool_name": "create_refund_review_tool",
                    "arguments": {
                        "customer_id": "cus_test",
                        "policy_id": "policy_test",
                        "reason": "reason",
                        "amount_usd": 20,
                        "evidence_ids": ["cus_test"],
                    },
                },
                {
                    "tool_name": "create_quality_exception_review_tool",
                    "arguments": {
                        "customer_id": "cus_test",
                        "order_id": "ord_test",
                        "reason": "reason",
                        "evidence_ids": ["ord_test"],
                    },
                },
            ],
        )

    def test_mcp_support_tools_client_raises_structured_tool_errors(self) -> None:
        async def call_tool(tool_name: str, arguments: dict) -> dict:
            return {
                "ok": False,
                "error": {
                    "type": "TimeoutError",
                    "message": "support-tools-mcp did not respond within 1500ms",
                },
            }

        client = McpSupportToolsClient(server_url="http://mcp.test/mcp/", call_tool=call_tool)

        with self.assertRaisesRegex(TimeoutError, "support-tools-mcp did not respond"):
            client.lookup_customer("timeout@example.com")

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
