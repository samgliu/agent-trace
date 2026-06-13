"""Support triage multi-agent workflow runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agenttrace.core.models import Span, Trace
from agent_apps.customer_service.agent_decisions import (
    action_agent_instructions as _action_agent_instructions,
    agent_decision_span_data as _agent_decision_span_data,
    deterministic_decision_response as _deterministic_decision_response,
    escalation_agent_instructions as _escalation_agent_instructions,
    investigation_agent_instructions as _investigation_agent_instructions,
    json_for_prompt as _json_for_prompt,
    model_call_span_data as _model_call_span_data,
    parse_agent_json as _parse_agent_json,
    policy_agent_instructions as _policy_agent_instructions,
    supervisor_instructions as _supervisor_instructions,
    triage_instructions as _triage_instructions,
    validator_agent_instructions as _validator_agent_instructions,
)
from agent_apps.customer_service.model_client import (
    LLMClient,
    LLMResponse,
    OpenAIChatCompletionsClient,
    OpenAIResponsesClient,
    _provider_http_error_message,
    resolve_model_config,
)
from agent_apps.customer_service.policy_logic import (
    AgentState,
    abuse_risk as _abuse_risk,
    action_plan as _action_plan,
    agent_state as _agent_state,
    approval_reason as _approval_reason,
    conversation_context as _conversation_context,
    create_domain_action as _create_domain_action,
    customer_memory as _customer_memory,
    enforce_validation as _enforce_validation,
    extract_order_number as _extract_order_number,
    grounding_evidence as _grounding_evidence,
    has_account_mismatch as _has_account_mismatch,
    investigation_plan as _investigation_plan,
    mcp_span_data as _mcp_span_data,
    policy_topic as _policy_topic,
    triage as _triage,
    validate_action_decision as _validate_action_decision,
    validate_investigation_plan as _validate_investigation_plan,
    validate_policy_decision as _validate_policy_decision,
    validate_triage_decision as _validate_triage_decision,
    working_memory as _working_memory,
)
from agent_apps.customer_service.response_generation import (
    clarification_response_input as _clarification_response_input,
    clarification_response_instructions as _clarification_response_instructions,
    clarification_response_safety as _clarification_response_safety,
    customer_response_input as _customer_response_input,
    customer_response_instructions as _customer_response_instructions,
    customer_response_safety as _customer_response_safety,
)
from agent_apps.customer_service.routing import (
    CLARIFY_REQUEST_ROUTE,
    fallback_supervisor_decision as _fallback_supervisor_decision,
    validate_supervisor_decision as _validate_supervisor_decision,
)
from agent_apps.customer_service.static_llm import StaticLLMClient
from agent_apps.customer_service.support_tools import LocalSupportToolsClient, McpSupportToolsClient, SupportToolsClient
from agent_apps.customer_service.trace_builder import span as _span
from agent_apps.customer_service.workflow_context import WorkflowRunContext


@dataclass(frozen=True)
class SupportTriageRunRequest:
    message: str
    customer_email: str
    trace_id: str | None = None
    use_openai: bool = False
    openai_api: str = "chat_completions"


class SupportTriageRunner:
    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        tools_client: SupportToolsClient | None = None,
        use_llm_agents: bool = False,
    ) -> None:
        self.llm_client = llm_client or StaticLLMClient()
        self.tools_client = tools_client or LocalSupportToolsClient()
        self.use_llm_agents = use_llm_agents

    def run(
        self,
        *,
        message: str,
        customer_email: str,
        trace_id: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        on_span: Callable[[Span], None] | None = None,
    ) -> Trace:
        conversation_history = conversation_history or []
        context = WorkflowRunContext.create(
            trace_id=trace_id,
            conversation_history_count=len(conversation_history),
            on_span=on_span,
        )
        trace_id = context.trace_id
        clock = context.clock
        span_ids = context.span_ids
        emit = context.emit

        supervisor_decision, supervisor_llm = self._agent_decision(
            agent_name="Supervisor Agent",
            instructions=_supervisor_instructions(),
            input_data={"message": message, "customer_email": customer_email, "conversation_history": conversation_history},
            fallback=_fallback_supervisor_decision(message, conversation_history),
            allowed_keys={"route", "handoff_reason"},
        )
        supervisor_decision, supervisor_validation = _validate_supervisor_decision(
            supervisor_decision,
            message=message,
            conversation_history=conversation_history,
        )
        supervisor_route = str(supervisor_decision["route"])
        supervisor = _span(
            trace_id=trace_id,
            span_id=span_ids["supervisor"],
            name="Supervisor Agent",
            span_type="agent",
            clock=clock,
            duration_ms=250,
            input={"message": message, "customer_email": customer_email, "conversation_history": conversation_history},
            output=supervisor_decision,
            span_data={
                "agent_role": "supervisor",
                "model_provider": self.llm_client.provider_name,
                **_agent_decision_span_data(supervisor_llm),
                **supervisor_validation,
                "supervisor_route": supervisor_route,
            },
            input_tokens=supervisor_llm.input_tokens,
            output_tokens=supervisor_llm.output_tokens,
            estimated_cost=supervisor_llm.estimated_cost,
        )
        emit(supervisor)
        if supervisor_route == CLARIFY_REQUEST_ROUTE:
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["handoff_response"],
                    name="Supervisor -> Customer Response Generator",
                    span_type="handoff",
                    parent_id=span_ids["investigation_agent"],
                    clock=clock,
                    duration_ms=75,
                    span_data={
                        "from_agent": "Supervisor Agent",
                        "to_agent": "Customer Response Generator",
                        "supervisor_route": supervisor_route,
                    },
                )
            )
            llm_response = self.llm_client.generate(
                instructions=_clarification_response_instructions(),
                input_text=_clarification_response_input(message, conversation_history),
            )
            response_text = _clarification_response_safety(llm_response.output_text)
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["customer_response"],
                    name="Customer Response Generator",
                    span_type="generation",
                    parent_id=supervisor.span_id,
                    clock=clock,
                    duration_ms=350,
                    input={"message": message},
                    output={"response": response_text},
                    span_data={
                        "agent_role": "response",
                        "supervisor_route": supervisor_route,
                        "model_provider": self.llm_client.provider_name,
                        **_model_call_span_data(llm_response.raw_response),
                        "raw_response": llm_response.raw_response,
                    },
                    input_tokens=llm_response.input_tokens,
                    output_tokens=llm_response.output_tokens,
                    estimated_cost=llm_response.estimated_cost,
                )
            )
            return context.finish(
                status="passed",
                llm_provider=self.llm_client.provider_name,
                agent_decision_mode="llm" if self.use_llm_agents else "deterministic",
                supervisor_route=supervisor_route,
            )
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["handoff_triage"],
                name="Supervisor -> Triage Agent",
                span_type="handoff",
                parent_id=span_ids["investigation_agent"],
                clock=clock,
                duration_ms=75,
                span_data={"from_agent": "Supervisor Agent", "to_agent": "Triage Agent"},
            )
        )

        triage_context = _conversation_context(message, conversation_history)
        triage, triage_llm = self._agent_decision(
            agent_name="Triage Agent",
            instructions=_triage_instructions(),
            input_data={"message": message, "recent_context": triage_context},
            fallback=_triage(message, conversation_history),
            allowed_keys={"issue_type", "urgency", "sentiment", "missing_information"},
        )
        triage_validation = _validate_triage_decision(message, triage, conversation_history)
        if triage_validation:
            triage = {**triage, **_triage(message, conversation_history)}
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["triage"],
                name="Triage Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=400,
                input={"message": message, "recent_context": triage_context},
                output=triage,
                span_data={
                    "agent_role": "triage",
                    "model_provider": self.llm_client.provider_name,
                    **_agent_decision_span_data(triage_llm),
                    **triage_validation,
                },
                input_tokens=triage_llm.input_tokens,
                output_tokens=triage_llm.output_tokens,
                estimated_cost=triage_llm.estimated_cost,
            )
        )
        agent_state = _agent_state(triage=triage)
        working_memory = _working_memory(message, customer_email, triage, conversation_history, agent_state)
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["working_memory_write"],
                name="Write Working Memory",
                span_type="memory_write",
                parent_id=span_ids["triage"],
                clock=clock,
                duration_ms=50,
                input={"message": message, "triage": triage},
                output=working_memory,
                span_data={
                    "memory_type": "short_term",
                    "memory_operation": "write",
                    "memory_store": "conversation_working_memory",
                    "memory_key": working_memory["memory_key"],
                    "memory_used_in_response": True,
                },
            )
        )
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["handoff_investigation"],
                name="Supervisor -> Investigation Agent",
                span_type="handoff",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=75,
                span_data={"from_agent": "Supervisor Agent", "to_agent": "Investigation Agent"},
            )
        )
        expected_investigation = _investigation_plan(
            message=message,
            triage_result=triage,
            conversation_history=conversation_history,
        )
        investigation, investigation_llm = self._agent_decision(
            agent_name="Investigation Agent",
            instructions=_investigation_agent_instructions(),
            input_data={
                "message": message,
                "triage": triage,
                "recent_context": triage_context,
                "known_order_number": _extract_order_number(message),
            },
            fallback=expected_investigation,
            allowed_keys={"required_evidence", "reason"},
        )
        investigation, investigation_validation = _validate_investigation_plan(
            investigation,
            message=message,
            triage_result=triage,
            conversation_history=conversation_history,
        )
        required_evidence = set(str(item) for item in investigation.get("required_evidence", []))
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["investigation_agent"],
                name="Investigation Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=325,
                input={"message": message, "triage": triage, "recent_context": triage_context},
                output=investigation,
                span_data={
                    "agent_role": "investigation",
                    "model_provider": self.llm_client.provider_name,
                    **_agent_decision_span_data(investigation_llm),
                    **investigation_validation,
                },
                input_tokens=investigation_llm.input_tokens,
                output_tokens=investigation_llm.output_tokens,
                estimated_cost=investigation_llm.estimated_cost,
            )
        )

        try:
            customer = self.tools_client.lookup_customer(customer_email)
        except Exception as exc:
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["lookup_customer"],
                    name="lookup_customer",
                    span_type="function_tool",
                    parent_id=supervisor.span_id,
                    clock=clock,
                    duration_ms=150,
                    input={"email": customer_email},
                    error={"type": exc.__class__.__name__, "message": str(exc)},
                    span_data=_mcp_span_data("lookup_customer_tool"),
                )
            )
            self._emit_escalation_agent(
                context,
                parent_id=span_ids["lookup_customer"],
                from_agent="Support Tool Recovery",
                escalation_input={
                    "message": message,
                    "customer_email": customer_email,
                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                    "agent_state": agent_state.to_dict(),
                },
                fallback={
                    "escalation_type": "technical_recovery",
                    "reason": "Customer lookup failed before the workflow could safely continue.",
                    "handoff_summary": "Support tools failed during customer lookup. A human should review the request and retry account verification.",
                    "next_owner": "support_operations",
                    "evidence": list(agent_state.evidence_ids),
                },
            )
            return context.finish(
                status="failed",
                llm_provider=self.llm_client.provider_name,
                agent_decision_mode="llm" if self.use_llm_agents else "deterministic",
                supervisor_route=supervisor_route,
            )

        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["lookup_customer"],
                name="lookup_customer",
                span_type="function_tool",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=150,
                input={"email": customer_email},
                output=customer,
                span_data=_mcp_span_data("lookup_customer_tool"),
            )
        )
        order_number = _extract_order_number(message)
        order: dict[str, Any] | None = None
        order_owner: dict[str, Any] | None = None
        charge: dict[str, Any] | None = None
        if "charge" in required_evidence:
            charge = self.tools_client.lookup_charge(str(customer.get("customer_id") or "unknown"))
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["lookup_charge"],
                    name="lookup_charge",
                    span_type="function_tool",
                    parent_id=span_ids["investigation_agent"],
                    clock=clock,
                    duration_ms=125,
                    input={"customer_id": customer.get("customer_id"), "charge_id": None},
                    output=charge,
                    span_data=_mcp_span_data("lookup_charge_tool"),
                )
            )
        if order_number and "order" in required_evidence:
            order = self.tools_client.lookup_order(order_number)
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["lookup_order"],
                    name="lookup_order",
                    span_type="function_tool",
                    parent_id=span_ids["investigation_agent"],
                    clock=clock,
                    duration_ms=120,
                    input={"order_number": order_number},
                    output=order,
                    span_data=_mcp_span_data("lookup_order_tool"),
                )
            )
        if order_number and "order_owner" in required_evidence:
            order_owner = self.tools_client.verify_order_owner(
                order_number,
                str(customer.get("customer_id") or "unknown"),
            )
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["verify_order_owner"],
                    name="verify_order_owner",
                    span_type="function_tool",
                    parent_id=span_ids["lookup_order"],
                    clock=clock,
                    duration_ms=90,
                    input={"order_number": order_number, "customer_id": customer.get("customer_id")},
                    output=order_owner,
                    span_data=_mcp_span_data("verify_order_owner_tool"),
                )
            )
        account_access: dict[str, Any] | None = None
        if "account_access" in required_evidence:
            account_access = self.tools_client.verify_account_access(
                str(customer.get("customer_id") or "unknown"),
                message,
            )
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["verify_account_access"],
                    name="verify_account_access",
                    span_type="function_tool",
                    parent_id=supervisor.span_id,
                    clock=clock,
                    duration_ms=100,
                    input={"customer_id": customer.get("customer_id"), "requested_account_hint": message},
                    output=account_access,
                    span_data=_mcp_span_data("verify_account_access_tool"),
                )
            )
        agent_state = _agent_state(
            triage=triage,
            customer=customer,
            order=order,
            order_owner=order_owner,
            charge=charge,
            account_access=account_access,
        )
        subscription: dict[str, Any] | None = None
        if "subscription" in required_evidence:
            subscription = self.tools_client.lookup_subscription(str(customer.get("customer_id") or "unknown"))
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["lookup_subscription"],
                    name="lookup_subscription",
                    span_type="function_tool",
                    parent_id=supervisor.span_id,
                    clock=clock,
                    duration_ms=110,
                    input={"customer_id": customer.get("customer_id")},
                    output=subscription,
                    span_data=_mcp_span_data("lookup_subscription_tool"),
                )
            )
            agent_state = _agent_state(
                triage=triage,
                customer=customer,
                order=order,
                order_owner=order_owner,
                charge=charge,
                account_access=account_access,
                subscription=subscription,
            )
        working_memory["agent_state"] = agent_state.to_dict()
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["handoff_policy"],
                name="Supervisor -> Policy Agent",
                span_type="handoff",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=75,
                span_data={"from_agent": "Supervisor Agent", "to_agent": "Policy Agent"},
            )
        )

        policy_plan, policy_llm = self._agent_decision(
            agent_name="Policy Agent",
            instructions=_policy_agent_instructions(),
            input_data={"triage": triage, "customer": customer},
            fallback={
                "retrieval_query": _policy_topic(triage, customer),
                "reason": "Deterministic policy routing selected the retrieval topic.",
            },
            allowed_keys={"retrieval_query", "reason"},
        )
        expected_policy_topic = _policy_topic(triage, customer)
        policy_topic = str(policy_plan.get("retrieval_query") or expected_policy_topic)
        policy_validation = _validate_policy_decision(policy_topic, expected_policy_topic)
        if policy_validation:
            policy_topic = expected_policy_topic
            policy_plan = {
                **policy_plan,
                "retrieval_query": expected_policy_topic,
                "reason": "Corrected to the policy topic implied by the customer message and triage result.",
            }
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["policy_agent"],
                name="Policy Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=350,
                input={"topic": policy_topic},
                output=policy_plan,
                span_data={
                    "agent_role": "policy",
                    "model_provider": self.llm_client.provider_name,
                    **_agent_decision_span_data(policy_llm),
                    **policy_validation,
                },
                input_tokens=policy_llm.input_tokens,
                output_tokens=policy_llm.output_tokens,
                estimated_cost=policy_llm.estimated_cost,
            )
        )
        policy = self.tools_client.retrieve_policy(policy_topic)
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["retrieve_policy"],
                name="retrieve_policy",
                span_type="rag_retrieval",
                parent_id=span_ids["policy_agent"],
                clock=clock,
                duration_ms=180,
                input={"topic": policy_topic},
                output=policy,
                span_data={"retriever": "mcp_policy_store", **_mcp_span_data("retrieve_policy_tool")},
            )
        )
        customer_memory = _customer_memory(customer, triage["issue_type"])
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["customer_memory_read"],
                name="Read Customer Memory",
                span_type="memory_read",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=80,
                input={"customer_id": customer.get("customer_id"), "issue_type": triage["issue_type"]},
                output=customer_memory,
                span_data={
                    "memory_type": "long_term",
                    "memory_operation": "read",
                    "memory_store": "customer_history",
                    "memory_key": str(customer.get("customer_id") or "unknown"),
                    "retrieved_memory_count": len(customer_memory["memories"]),
                    "memory_relevance_score": customer_memory["relevance_score"],
                    "memory_age_seconds": customer_memory["memory_age_seconds"],
                    "memory_used_in_response": customer_memory["used_in_response"],
                },
            )
        )

        expected_action = _action_plan(
            triage_result=triage,
            customer=customer,
            policy=policy,
            customer_memory=customer_memory,
            agent_state_value=agent_state,
        )
        action_decision, action_llm = self._agent_decision(
            agent_name="Action Agent",
            instructions=_action_agent_instructions(),
            input_data={
                "triage": triage,
                "customer": customer,
                "policy": policy,
                "memory": customer_memory,
                "agent_state": agent_state.to_dict(),
            },
            fallback=expected_action,
            allowed_keys={
                "action_type",
                "reason",
                "customer_outcome",
                "requires_human_review",
                "customer_message_goal",
                "policy_boundary",
                "evidence_used",
            },
        )
        action_decision, action_validation = _validate_action_decision(action_decision, policy, expected_action)
        action_type = str(action_decision["action_type"])
        action_reason = str(action_decision["reason"])
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["action_agent"],
                name="Action Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=450,
                input={
                    "issue_type": triage["issue_type"],
                    "policy": policy,
                    "memory": customer_memory,
                    "agent_state": agent_state.to_dict(),
                },
                output=action_decision,
                span_data={
                    "agent_role": "action",
                    "model_provider": self.llm_client.provider_name,
                    **_agent_decision_span_data(action_llm),
                    **action_validation,
                },
                input_tokens=action_llm.input_tokens,
                output_tokens=action_llm.output_tokens,
                estimated_cost=action_llm.estimated_cost,
            )
        )
        agent_state = _agent_state(
            triage=triage,
            customer=customer,
            order=order,
            order_owner=order_owner,
            charge=charge,
            account_access=account_access,
            subscription=subscription,
            proposed_action=action_type,
            policy=policy,
        )
        previous_agent_state = working_memory.get("agent_state")
        working_memory["agent_state"] = agent_state.to_dict()
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["agent_state_update"],
                name="Update Agent State",
                span_type="memory_write",
                parent_id=span_ids["action_agent"],
                clock=clock,
                duration_ms=50,
                input={"previous_state": previous_agent_state, "action_type": action_type},
                output=working_memory,
                span_data={
                    "memory_type": "short_term",
                    "memory_operation": "write",
                    "memory_store": "conversation_working_memory",
                    "memory_key": working_memory["memory_key"],
                    "memory_used_in_response": True,
                },
            )
        )
        action, action_tool_name = _create_domain_action(
            self.tools_client,
            customer=customer,
            policy=policy,
            action_type=action_type,
            action_reason=action_reason,
            order=order,
            agent_state=agent_state,
        )
        action["resolution_plan"] = {
            "customer_outcome": action_decision.get("customer_outcome"),
            "requires_human_review": action_decision.get("requires_human_review"),
            "customer_message_goal": action_decision.get("customer_message_goal"),
            "policy_boundary": action_decision.get("policy_boundary"),
            "evidence_used": action_decision.get("evidence_used", []),
        }
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["create_action"],
                name=action_tool_name.removesuffix("_tool"),
                span_type="function_tool",
                parent_id=span_ids["action_agent"],
                clock=clock,
                duration_ms=150,
                input={
                    "customer_id": customer.get("customer_id"),
                    "action_type": action_type,
                    "reason": action_reason,
                    "evidence_ids": list(agent_state.evidence_ids),
                    "resolution_plan": action.get("resolution_plan"),
                },
                output=action,
                span_data=_mcp_span_data(action_tool_name),
            )
        )

        requires_approval = bool(policy.get("requires_approval"))
        abuse_risk = _abuse_risk(customer, policy)
        validation_evidence = list(dict.fromkeys([*agent_state.evidence_ids, action.get("action_id")]))
        validation_fallback = {
            "grounding_status": "recovered" if requires_approval else "grounded",
            "approval_required": requires_approval,
            "evidence": validation_evidence,
            "grounding_evidence": _grounding_evidence(customer, policy, action),
            "allowed_actions": policy.get("allowed_actions", []),
            "customer_friendly_resolution": policy.get("customer_friendly_resolution"),
            "abuse_risk": abuse_risk,
            "risk_review_required": abuse_risk["requires_human_review"],
        }
        validation, validation_llm = self._agent_decision(
            agent_name="Validator Agent",
            instructions=_validator_agent_instructions(),
            input_data={"customer": customer, "policy": policy, "action": action, "fallback": validation_fallback},
            fallback=validation_fallback,
            allowed_keys={"grounding_status", "approval_required", "evidence", "unsupported_claims"},
        )
        validation = _enforce_validation(policy, action, validation, validation_fallback)
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["validator"],
                name="Validator Agent",
                span_type="guardrail",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=300,
                input={"customer": customer, "policy": policy, "action": action},
                output=validation,
                span_data={
                    "agent_role": "validator",
                    "model_provider": self.llm_client.provider_name,
                    **validation,
                    **_agent_decision_span_data(validation_llm),
                },
                input_tokens=validation_llm.input_tokens,
                output_tokens=validation_llm.output_tokens,
                estimated_cost=validation_llm.estimated_cost,
            )
        )
        escalation: dict[str, Any] | None = None
        if action_type == "escalation" or validation.get("risk_review_required"):
            escalation = self._emit_escalation_agent(
                context,
                parent_id=span_ids["validator"],
                from_agent="Validator Agent",
                escalation_input={
                    "message": message,
                    "customer": customer,
                    "policy": policy,
                    "action": action,
                    "validation": validation,
                    "agent_state": agent_state.to_dict(),
                    "customer_memory": customer_memory,
                },
                fallback=self._escalation_fallback(
                    action=action,
                    validation=validation,
                    agent_state=agent_state,
                ),
            )
        if validation["approval_required"]:
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["approval_required"],
                    name="Human Approval Gate",
                    span_type="approval",
                    parent_id=span_ids["validator"],
                    clock=clock,
                    duration_ms=100,
                    input={"policy_id": policy.get("policy_id"), "action_id": action.get("action_id")},
                    output={"approval_status": "blocked", "reason": _approval_reason(validation)},
                    span_data={
                        "approval_required": True,
                        "approval_status": "blocked",
                        "policy_id": policy.get("policy_id"),
                        "action_id": action.get("action_id"),
                        "risk_review_required": validation.get("risk_review_required", False),
                        "escalation_type": escalation.get("escalation_type") if escalation else None,
                    },
                )
            )

        llm_response = self.llm_client.generate(
            instructions=_customer_response_instructions(),
            input_text=_customer_response_input(message, customer, policy, action, validation, working_memory, customer_memory),
        )
        response_text = _customer_response_safety(
            llm_response.output_text,
            policy=policy,
            action=action,
            working_memory=working_memory,
        )
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["customer_response"],
                name="Customer Response Generator",
                span_type="generation",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=650,
                input={"message": message},
                output={"response": response_text},
                span_data={
                    "model_provider": self.llm_client.provider_name,
                    **_model_call_span_data(llm_response.raw_response),
                    "raw_response": llm_response.raw_response,
                },
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                estimated_cost=llm_response.estimated_cost,
            )
        )

        return context.finish(
            status="recovered" if validation["approval_required"] else "passed",
            llm_provider=self.llm_client.provider_name,
            agent_decision_mode="llm" if self.use_llm_agents else "deterministic",
            supervisor_route=supervisor_route,
        )

    def _agent_decision(
        self,
        *,
        agent_name: str,
        instructions: str,
        input_data: dict[str, Any],
        fallback: dict[str, Any],
        allowed_keys: set[str],
    ) -> tuple[dict[str, Any], LLMResponse]:
        if not self.use_llm_agents:
            return fallback, _deterministic_decision_response(fallback)
        response = self.llm_client.generate(
            instructions=instructions,
            input_text=_json_for_prompt(input_data),
        )
        parsed = _parse_agent_json(response.output_text)
        if parsed is None:
            return fallback, LLMResponse(
                output_text=response.output_text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                estimated_cost=response.estimated_cost,
                raw_response={
                    "agent": agent_name,
                    "decision_source": "fallback",
                    "fallback_reason": "invalid_json",
                    "model_output_text": response.output_text,
                    "raw_response": response.raw_response,
                },
            )
        decision = {key: parsed[key] for key in allowed_keys if key in parsed}
        return {**fallback, **decision}, LLMResponse(
            output_text=response.output_text,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost=response.estimated_cost,
            raw_response={
                "agent": agent_name,
                "decision_source": "llm",
                "model_output_text": response.output_text,
                "raw_response": response.raw_response,
            },
        )

    def _emit_escalation_agent(
        self,
        context: WorkflowRunContext,
        *,
        parent_id: str,
        from_agent: str,
        escalation_input: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        span_ids = context.span_ids
        context.emit(
            _span(
                trace_id=context.trace_id,
                span_id=span_ids["handoff_escalation"],
                name=f"{from_agent} -> Escalation Agent",
                span_type="handoff",
                parent_id=parent_id,
                clock=context.clock,
                duration_ms=75,
                span_data={
                    "from_agent": from_agent,
                    "to_agent": "Escalation Agent",
                },
            )
        )
        escalation, escalation_llm = self._agent_decision(
            agent_name="Escalation Agent",
            instructions=_escalation_agent_instructions(),
            input_data=escalation_input,
            fallback=fallback,
            allowed_keys={"escalation_type", "reason", "handoff_summary", "next_owner", "evidence"},
        )
        escalation = _canonical_escalation(escalation, fallback)
        context.emit(
            _span(
                trace_id=context.trace_id,
                span_id=span_ids["escalation_agent"],
                name="Escalation Agent",
                span_type="agent",
                parent_id=parent_id,
                clock=context.clock,
                duration_ms=300,
                input=escalation_input,
                output=escalation,
                span_data={
                    "agent_role": "escalation",
                    "model_provider": self.llm_client.provider_name,
                    "escalation_type": escalation.get("escalation_type"),
                    "next_owner": escalation.get("next_owner"),
                    **_agent_decision_span_data(escalation_llm),
                },
                input_tokens=escalation_llm.input_tokens,
                output_tokens=escalation_llm.output_tokens,
                estimated_cost=escalation_llm.estimated_cost,
            )
        )
        return escalation

    def _escalation_fallback(
        self,
        *,
        action: dict[str, Any],
        validation: dict[str, Any],
        agent_state: AgentState,
    ) -> dict[str, Any]:
        validation_evidence = validation.get("evidence")
        if not isinstance(validation_evidence, list):
            validation_evidence = []
        evidence = list(dict.fromkeys([*agent_state.evidence_ids, *[str(item) for item in validation_evidence]]))
        if validation.get("risk_review_required"):
            return {
                "escalation_type": "risk_review",
                "reason": "Abuse-risk controls require human review before the workflow can finish.",
                "handoff_summary": "Review the refund request, risk signals, policy evidence, and proposed action before customer-impacting execution.",
                "next_owner": "trust_and_safety",
                "evidence": evidence,
            }
        return {
            "escalation_type": "human_review",
            "reason": str(action.get("reason") or "The customer requested human support or the issue needs manual review."),
            "handoff_summary": "Human support should review the active issue, evidence, and proposed escalation action.",
            "next_owner": "support_specialist",
            "evidence": evidence,
        }


def _canonical_escalation(escalation: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(escalation)
    fallback_type = str(fallback.get("escalation_type") or "")
    raw_type = str(canonical.get("escalation_type") or "").lower()
    raw_owner = str(canonical.get("next_owner") or "").lower()
    raw_reason = str(canonical.get("reason") or "")

    if fallback_type == "technical_recovery" or "technical" in raw_type or "support-tools-mcp" in raw_reason.lower():
        canonical["escalation_type"] = "technical_recovery"
        canonical["next_owner"] = "support_operations"
        if "lookup failed" not in raw_reason.lower():
            canonical["reason"] = "Customer lookup failed before the workflow could safely continue."
    elif fallback_type == "risk_review" or "risk" in raw_type or "abuse" in raw_type or "risk" in raw_owner or "abuse" in raw_owner:
        canonical["escalation_type"] = "risk_review"
        canonical["next_owner"] = "trust_and_safety"
        if "abuse-risk controls" not in raw_reason.lower():
            canonical["reason"] = "Abuse-risk controls require human review before the workflow can finish."
    elif fallback_type == "human_review":
        canonical["escalation_type"] = "human_review"
        canonical["next_owner"] = "support_specialist"

    if not isinstance(canonical.get("evidence"), list):
        canonical["evidence"] = fallback.get("evidence", [])
    if not canonical.get("handoff_summary"):
        canonical["handoff_summary"] = fallback.get("handoff_summary", "")
    return canonical


def build_default_runner(*, use_openai: bool = False, openai_api: str = "chat_completions") -> SupportTriageRunner:
    from agent_apps.customer_service.default_runner import build_default_runner as _build_default_runner

    return _build_default_runner(use_openai=use_openai, openai_api=openai_api)


def _llm_timeout_seconds() -> float:
    from agent_apps.customer_service.default_runner import llm_timeout_seconds

    return llm_timeout_seconds()
