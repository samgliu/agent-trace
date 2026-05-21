"""Support triage multi-agent workflow runner."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from agenttrace.core.models import Span, Trace
from agent_apps.customer_service.agent_decisions import (
    action_agent_instructions as _action_agent_instructions,
    agent_decision_span_data as _agent_decision_span_data,
    deterministic_decision_response as _deterministic_decision_response,
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
    action_reason as _action_reason,
    action_type as _action_type,
    agent_state as _agent_state,
    approval_reason as _approval_reason,
    conversation_context as _conversation_context,
    create_domain_action as _create_domain_action,
    customer_memory as _customer_memory,
    enforce_validation as _enforce_validation,
    extract_order_number as _extract_order_number,
    grounding_evidence as _grounding_evidence,
    has_account_mismatch as _has_account_mismatch,
    mcp_span_data as _mcp_span_data,
    policy_topic as _policy_topic,
    triage as _triage,
    validate_action_decision as _validate_action_decision,
    validate_policy_decision as _validate_policy_decision,
    validate_triage_decision as _validate_triage_decision,
    working_memory as _working_memory,
)
from agent_apps.customer_service.response_generation import (
    customer_response_input as _customer_response_input,
    customer_response_instructions as _customer_response_instructions,
    customer_response_safety as _customer_response_safety,
)
from agent_apps.customer_service.static_llm import StaticLLMClient
from agent_apps.customer_service.support_tools import LocalSupportToolsClient, McpSupportToolsClient, SupportToolsClient
from agent_apps.customer_service.trace_builder import SpanClock as _SpanClock
from agent_apps.customer_service.trace_builder import span as _span
from agent_apps.customer_service.trace_builder import span_id as _span_id
from agent_apps.customer_service.trace_builder import trace as _trace


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
        trace_id = trace_id or f"trace_support_triage_{uuid.uuid4().hex[:12]}"
        conversation_history = conversation_history or []
        clock = _SpanClock(datetime.now(timezone.utc))
        spans: list[Span] = []
        emitted_span_ids: set[str] = set()

        def emit(span: Span) -> Span:
            spans.append(span)
            if on_span is not None and span.span_id not in emitted_span_ids:
                emitted_span_ids.add(span.span_id)
                on_span(span)
            return span

        span_ids = {
            "supervisor": _span_id(trace_id, "supervisor"),
            "handoff_triage": _span_id(trace_id, "handoff_triage"),
            "triage": _span_id(trace_id, "triage"),
            "working_memory_write": _span_id(trace_id, "working_memory_write"),
            "lookup_customer": _span_id(trace_id, "lookup_customer"),
            "lookup_order": _span_id(trace_id, "lookup_order"),
            "verify_order_owner": _span_id(trace_id, "verify_order_owner"),
            "verify_account_access": _span_id(trace_id, "verify_account_access"),
            "lookup_subscription": _span_id(trace_id, "lookup_subscription"),
            "handoff_policy": _span_id(trace_id, "handoff_policy"),
            "policy_agent": _span_id(trace_id, "policy_agent"),
            "retrieve_policy": _span_id(trace_id, "retrieve_policy"),
            "customer_memory_read": _span_id(trace_id, "customer_memory_read"),
            "action_agent": _span_id(trace_id, "action_agent"),
            "agent_state_update": _span_id(trace_id, "agent_state_update"),
            "create_action": _span_id(trace_id, "create_action"),
            "validator": _span_id(trace_id, "validator"),
            "approval_required": _span_id(trace_id, "approval_required"),
            "customer_response": _span_id(trace_id, "customer_response"),
        }

        supervisor_decision, supervisor_llm = self._agent_decision(
            agent_name="Supervisor Agent",
            instructions=_supervisor_instructions(),
            input_data={"message": message, "customer_email": customer_email, "conversation_history": conversation_history},
            fallback={"route": "triage", "handoff_reason": "Initial customer request requires triage."},
            allowed_keys={"route", "handoff_reason"},
        )
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
            },
            input_tokens=supervisor_llm.input_tokens,
            output_tokens=supervisor_llm.output_tokens,
            estimated_cost=supervisor_llm.estimated_cost,
        )
        emit(supervisor)
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["handoff_triage"],
                name="Supervisor -> Triage Agent",
                span_type="handoff",
                parent_id=supervisor.span_id,
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
            return _trace(
                trace_id=trace_id,
                status="failed",
                started_at=spans[0].started_at,
                ended_at=spans[-1].ended_at,
                spans=spans,
                llm_provider=self.llm_client.provider_name,
                agent_decision_mode="llm" if self.use_llm_agents else "deterministic",
                conversation_history_count=len(conversation_history),
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
        if order_number:
            order = self.tools_client.lookup_order(order_number)
            emit(
                _span(
                    trace_id=trace_id,
                    span_id=span_ids["lookup_order"],
                    name="lookup_order",
                    span_type="function_tool",
                    parent_id=supervisor.span_id,
                    clock=clock,
                    duration_ms=120,
                    input={"order_number": order_number},
                    output=order,
                    span_data=_mcp_span_data("lookup_order_tool"),
                )
            )
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
        if _has_account_mismatch(message.lower()):
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
            account_access=account_access,
        )
        subscription: dict[str, Any] | None = None
        if triage["issue_type"] in {"annual_plan_refund", "stale_subscription_refund"}:
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

        expected_action = {
            "action_type": _action_type(triage, customer),
            "reason": _action_reason(triage, customer, policy, customer_memory),
        }
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
            allowed_keys={"action_type", "reason"},
        )
        action_type = str(action_decision.get("action_type") or expected_action["action_type"])
        action_reason = str(action_decision.get("reason") or expected_action["reason"])
        action_validation = _validate_action_decision(action_type, policy, expected_action["action_type"])
        if action_validation:
            action_type = expected_action["action_type"]
            action_reason = expected_action["reason"]
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
                output={"action_type": action_type, "reason": action_reason},
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

        return _trace(
            trace_id=trace_id,
            status="recovered" if validation["approval_required"] else "passed",
            started_at=spans[0].started_at,
            ended_at=spans[-1].ended_at,
            spans=spans,
            llm_provider=self.llm_client.provider_name,
            agent_decision_mode="llm" if self.use_llm_agents else "deterministic",
            conversation_history_count=len(conversation_history),
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


def build_default_runner(*, use_openai: bool = False, openai_api: str = "chat_completions") -> SupportTriageRunner:
    from agent_apps.customer_service.default_runner import build_default_runner as _build_default_runner

    return _build_default_runner(use_openai=use_openai, openai_api=openai_api)


def _llm_timeout_seconds() -> float:
    from agent_apps.customer_service.default_runner import llm_timeout_seconds

    return llm_timeout_seconds()
