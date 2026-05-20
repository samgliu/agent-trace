"""Support triage multi-agent workflow runner."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agent_apps.customer_service.domain import VALID_ACTIONS
from agent_apps.customer_service.model_client import (
    LLMClient,
    LLMResponse,
    OpenAIChatCompletionsClient,
    OpenAIResponsesClient,
    _provider_http_error_message,
    resolve_model_config,
)
from agent_apps.customer_service.support_tools import LocalSupportToolsClient, McpSupportToolsClient, SupportToolsClient


@dataclass(frozen=True)
class AgentState:
    active_issue: str
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    risk_signals: tuple[str, ...] = ()
    proposed_action: str | None = None
    next_required_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_issue": self.active_issue,
            "missing_fields": list(self.missing_fields),
            "evidence_ids": list(self.evidence_ids),
            "risk_signals": list(self.risk_signals),
            "proposed_action": self.proposed_action,
            "next_required_step": self.next_required_step,
        }


class StaticLLMClient(LLMClient):
    provider_name = "static"

    def __init__(self, output_text: str | None = None) -> None:
        self.output_text = output_text or (
            "Thanks for the details. I reviewed the account and policy context, "
            "and created the next support action for review."
        )

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        output_text = self.output_text
        if "Customer message:" in input_text:
            output_text = _static_customer_response(input_text, self.output_text)
        return LLMResponse(
            output_text=output_text,
            input_tokens=_rough_token_count(instructions + "\n" + input_text),
            output_tokens=_rough_token_count(output_text),
            estimated_cost=0.0,
            raw_response={"provider": self.provider_name},
        )


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
    if not use_openai:
        llm_client: LLMClient = StaticLLMClient()
    elif openai_api == "responses":
        llm_client = OpenAIResponsesClient(timeout_seconds=_llm_timeout_seconds())
    else:
        llm_client = OpenAIChatCompletionsClient(timeout_seconds=_llm_timeout_seconds())
    tools_client: SupportToolsClient
    if os.environ.get("AGENTTRACE_MCP_TOOLS_URL"):
        tools_client = McpSupportToolsClient()
    else:
        tools_client = LocalSupportToolsClient()
    return SupportTriageRunner(llm_client=llm_client, tools_client=tools_client, use_llm_agents=use_openai)


def _llm_timeout_seconds() -> float:
    raw_value = os.environ.get("AGENTTRACE_LLM_TIMEOUT_SECONDS", "180")
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return 180.0


def _trace(
    *,
    trace_id: str,
    status: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    spans: list[Span],
    llm_provider: str,
    agent_decision_mode: str,
    conversation_history_count: int = 0,
) -> Trace:
    trace = Trace(
        trace_id=trace_id,
        workflow_name="support-triage",
        status=status,
        metadata={
            "source": "agenttrace-agent-runner",
            "runner": "agent_apps.customer_service.runner",
            "llm_provider": llm_provider,
            "agent_decision_mode": agent_decision_mode,
            "conversation_history_count": conversation_history_count,
        },
        raw_payload=None,
        started_at=started_at,
        ended_at=ended_at,
        spans=spans,
    )
    return with_source_metadata(trace, source_format="agenttrace", source_kind="agent_runner")


def _span(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    span_type: str,
    clock: "_SpanClock",
    duration_ms: int,
    parent_id: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    span_data: dict[str, Any] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost: float | None = None,
) -> Span:
    started_at, ended_at = clock.next(duration_ms)
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        parent_id=parent_id,
        name=name,
        span_type=span_type,
        started_at=started_at,
        ended_at=ended_at,
        input=input,
        output=output,
        error=error,
        span_data=span_data or {},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )


def _span_id(trace_id: str, suffix: str) -> str:
    return f"{trace_id}_{suffix}"


class _SpanClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def next(self, duration_ms: int) -> tuple[datetime, datetime]:
        started_at = self.current
        ended_at = started_at + timedelta(milliseconds=duration_ms)
        self.current = ended_at
        return started_at, ended_at


def _conversation_context(message: str, conversation_history: list[dict[str, Any]] | None = None) -> str:
    recent_turns = conversation_history[-4:] if conversation_history else []
    parts = [str(turn.get("content") or "") for turn in recent_turns]
    parts.append(message)
    return "\n".join(part for part in parts if part).lower()


def _triage(message: str, conversation_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current_text = message.lower()
    text = _conversation_context(message, conversation_history)
    quality_exception = _has_quality_exception(text)
    if _has_account_mismatch(current_text):
        issue_type = "general_support"
        urgency = "medium"
    elif "charged twice" in current_text or "duplicate" in current_text:
        issue_type = "billing_duplicate_charge"
        urgency = "medium"
    elif ("return" in text or "refund" in text) and (
        "banana" in text or "bananas" in text or "grocery" in text or "product" in text or "item" in text
    ) and ("ate" in text or "eaten" in text or "consumed" in text or "used all" in text):
        issue_type = "consumed_product_return"
        urgency = "low"
    elif "charged twice" in text or "duplicate" in text:
        issue_type = "billing_duplicate_charge"
        urgency = "medium"
    elif ("refund" in text and "subscription" in text) and (
        "year ago" in text or "years ago" in text or "3 years" in text or "old charge" in text
    ):
        issue_type = "stale_subscription_refund"
        urgency = "medium"
    elif "annual" in text and "refund" in text:
        issue_type = "annual_plan_refund"
        urgency = "medium"
    elif "access" in text or "login" in text:
        issue_type = "account_access"
        urgency = "high"
    else:
        issue_type = "general_support"
        urgency = "low"
    result = {"issue_type": issue_type, "urgency": urgency, "sentiment": "concerned"}
    if quality_exception and issue_type == "consumed_product_return":
        result["quality_exception"] = True
    if issue_type == "general_support" and _has_account_mismatch(current_text):
        result["missing_information"] = "verified account or matching order ownership"
    return result


def _has_quality_exception(text: str) -> bool:
    return any(signal in text for signal in ("spoiled", "moldy", "mouldy", "rotten", "unsafe", "sick", "delivery issue"))


def _has_account_mismatch(text: str) -> bool:
    return any(signal in text for signal in ("different email", "another email", "spouse", "not my account", "wrong account"))


def _validation_correction(reason: str, **metadata: Any) -> dict[str, Any]:
    return {
        "decision_source": "policy_validation",
        "validation_reason": reason,
        **metadata,
    }


def _validate_triage_decision(
    message: str,
    triage: dict[str, Any],
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected = _triage(message, conversation_history)
    known_issue_types = {
        "account_access",
        "annual_plan_refund",
        "billing_duplicate_charge",
        "consumed_product_return",
        "general_support",
        "stale_subscription_refund",
    }
    if triage.get("issue_type") not in known_issue_types:
        return _validation_correction("unsupported_issue_type", rejected_issue_type=triage.get("issue_type"))
    if triage.get("issue_type") == expected["issue_type"]:
        if expected.get("quality_exception") and not triage.get("quality_exception"):
            return _validation_correction(
                "missing_quality_exception_signal",
                rejected_issue_type=triage.get("issue_type"),
            )
        return {}
    if expected["issue_type"] in {
        "account_access",
        "stale_subscription_refund",
        "billing_duplicate_charge",
        "annual_plan_refund",
        "consumed_product_return",
        "general_support",
    }:
        return _validation_correction(
            "message_policy_signal_mismatch",
            rejected_issue_type=triage.get("issue_type"),
        )
    return {}


def _policy_topic(triage: dict[str, Any], customer: dict[str, Any]) -> str:
    if triage["issue_type"] == "consumed_product_return":
        return "consumed_product_return"
    if triage["issue_type"] == "annual_plan_refund" or customer.get("annual_price_usd", 0) > 500:
        return "annual_plan_refund"
    if triage["issue_type"] == "stale_subscription_refund":
        return "stale_subscription_refund"
    if triage["issue_type"] == "billing_duplicate_charge":
        return "duplicate_charge_refund"
    return "general_support"


def _validate_policy_decision(policy_topic: str, expected_policy_topic: str) -> dict[str, Any]:
    if policy_topic == expected_policy_topic:
        return {}
    return _validation_correction("policy_topic_mismatch", rejected_policy_topic=policy_topic)


def _action_type(triage: dict[str, Any], customer: dict[str, Any]) -> str:
    if not customer.get("found"):
        return "clarification_request"
    if triage["issue_type"] == "account_access":
        return "escalation"
    if triage["issue_type"] == "consumed_product_return" and triage.get("quality_exception"):
        return "courtesy_credit"
    if triage["issue_type"] in {"general_support", "consumed_product_return"}:
        return "clarification_request"
    return "refund_review"


def _action_reason(
    triage: dict[str, Any],
    customer: dict[str, Any],
    policy: dict[str, Any],
    customer_memory: dict[str, Any],
) -> str:
    memory_note = ""
    if customer_memory.get("used_in_response"):
        memory_note = f" Memory context: {customer_memory['memories'][0]['summary']}"
    return (
        f"{triage['issue_type']} for {customer.get('customer_id', 'unknown customer')} "
        f"under {policy.get('policy_id', 'missing policy')}.{memory_note}"
    )


def _validate_action_decision(action_type: str, policy: dict[str, Any], expected_action_type: str) -> dict[str, Any]:
    normalized_action = action_type.strip().lower()
    if normalized_action not in VALID_ACTIONS:
        return _validation_correction("unsupported_action_type", rejected_action_type=action_type)
    allowed_actions = policy.get("allowed_actions")
    if isinstance(allowed_actions, list) and normalized_action not in allowed_actions:
        return _validation_correction(
            "action_not_allowed_by_policy",
            rejected_action_type=action_type,
            policy_allowed_actions=allowed_actions,
        )
    policy_id = str(policy.get("policy_id") or "")
    if (
        expected_action_type == "clarification_request"
        and policy_id == "policy_general_support"
        and normalized_action != "clarification_request"
    ):
        return _validation_correction(
            "clarification_required_by_policy_path",
            rejected_action_type=action_type,
            policy_id=policy_id,
        )
    if (
        expected_action_type == "courtesy_credit"
        and policy_id == "policy_consumed_product_return"
        and normalized_action != "courtesy_credit"
    ):
        return _validation_correction(
            "quality_exception_action_required",
            rejected_action_type=action_type,
            policy_id=policy_id,
        )
    if (
        expected_action_type == "refund_review"
        and policy_id
        in {
            "policy_refund_duplicate_charge",
            "policy_annual_refund",
            "policy_stale_subscription_refund",
        }
        and normalized_action != "refund_review"
    ):
        return _validation_correction(
            "refund_review_required_by_policy_path",
            rejected_action_type=action_type,
            policy_id=policy_id,
        )
    return {}


def _create_domain_action(
    tools_client: SupportToolsClient,
    *,
    customer: dict[str, Any],
    policy: dict[str, Any],
    action_type: str,
    action_reason: str,
    order: dict[str, Any] | None,
    agent_state: AgentState,
) -> tuple[dict[str, Any], str]:
    customer_id = str(customer.get("customer_id") or "unknown")
    evidence_ids = list(agent_state.evidence_ids)
    if action_type == "refund_review":
        amount = _refund_amount(customer, order)
        return (
            tools_client.create_refund_review(
                customer_id,
                str(policy.get("policy_id") or "policy_unknown"),
                action_reason,
                amount,
                evidence_ids,
            ),
            "create_refund_review_tool",
        )
    if action_type == "courtesy_credit" and order and order.get("order_id"):
        return (
            tools_client.create_quality_exception_review(
                customer_id,
                str(order["order_id"]),
                action_reason,
                evidence_ids,
            ),
            "create_quality_exception_review_tool",
        )
    return (
        tools_client.create_support_action(customer_id, action_type, action_reason),
        "create_support_action_tool",
    )


def _refund_amount(customer: dict[str, Any], order: dict[str, Any] | None) -> int | None:
    if order and isinstance(order.get("amount_usd"), int):
        return int(order["amount_usd"])
    for key in ("duplicate_charge_amount_usd", "annual_price_usd", "monthly_price_usd"):
        if isinstance(customer.get(key), int):
            return int(customer[key])
    return None


def _extract_order_number(message: str) -> str | None:
    match = re.search(r"(?:order(?:\s+number)?[:\s#]*|#)([A-Za-z0-9-]{3,20})", message, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _agent_state(
    *,
    triage: dict[str, Any],
    customer: dict[str, Any] | None = None,
    order: dict[str, Any] | None = None,
    order_owner: dict[str, Any] | None = None,
    account_access: dict[str, Any] | None = None,
    subscription: dict[str, Any] | None = None,
    proposed_action: str | None = None,
    policy: dict[str, Any] | None = None,
) -> AgentState:
    missing_fields: list[str] = []
    evidence_ids: list[str] = []
    risk_signals: list[str] = []
    issue_type = str(triage.get("issue_type") or "general_support")

    if triage.get("missing_information"):
        missing_fields.append(str(triage["missing_information"]))
    if customer:
        if customer.get("customer_id"):
            evidence_ids.append(str(customer["customer_id"]))
        if not customer.get("found", True):
            missing_fields.extend(str(field) for field in customer.get("missing_fields", []))
        prior_refunds = int(customer.get("prior_refunds_12m") or 0)
        chargebacks = int(customer.get("chargeback_count_12m") or 0)
        account_age_days = int(customer.get("account_age_days") or 0)
        if prior_refunds > 3:
            risk_signals.append("high_prior_refund_count")
        if chargebacks > 0:
            risk_signals.append("recent_chargebacks")
        if customer.get("found") and not customer.get("payment_method_verified", True):
            risk_signals.append("unverified_payment_method")
        if account_age_days and account_age_days < 30:
            risk_signals.append("new_account")
    if policy and policy.get("policy_id"):
        evidence_ids.append(str(policy["policy_id"]))
    if order:
        if order.get("order_id"):
            evidence_ids.append(str(order["order_id"]))
        if not order.get("found"):
            missing_fields.extend(str(field) for field in order.get("missing_fields", []))
    if order_owner:
        if order_owner.get("verified"):
            evidence_ids.append(str(order_owner.get("reason") or "order_customer_match"))
        else:
            risk_signals.append("order_customer_mismatch")
    if account_access:
        evidence_id = account_access.get("evidence_id")
        if evidence_id:
            evidence_ids.append(str(evidence_id))
        if not account_access.get("verified"):
            risk_signals.append(str(account_access.get("reason") or "account_access_mismatch"))
            missing_fields.extend(str(field) for field in account_access.get("missing_fields", []))
    if subscription:
        if subscription.get("subscription_id"):
            evidence_ids.append(str(subscription["subscription_id"]))
        if not subscription.get("found"):
            missing_fields.extend(str(field) for field in subscription.get("missing_fields", []))

    if issue_type == "consumed_product_return" and not order:
        missing_fields.append("order_number_or_receipt")
        if not triage.get("quality_exception"):
            missing_fields.append("product_issue_reason")

    next_required_step = "create_support_action"
    if missing_fields and proposed_action == "clarification_request":
        next_required_step = "collect_missing_information"
    elif policy and policy.get("requires_approval"):
        next_required_step = "human_approval"
    elif risk_signals:
        next_required_step = "human_review"

    return AgentState(
        active_issue=issue_type,
        missing_fields=tuple(dict.fromkeys(missing_fields)),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        risk_signals=tuple(dict.fromkeys(risk_signals)),
        proposed_action=proposed_action,
        next_required_step=next_required_step,
    )


def _enforce_validation(
    policy: dict[str, Any],
    action: dict[str, Any],
    validation: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    enforced = {**fallback, **validation}
    enforced["approval_required"] = bool(enforced.get("approval_required"))
    enforced["grounding_status"] = str(enforced.get("grounding_status") or fallback["grounding_status"])

    evidence = enforced.get("evidence")
    if not isinstance(evidence, list):
        enforced["evidence"] = fallback["evidence"]

    corrections = []
    if policy.get("requires_approval") and not enforced["approval_required"]:
        enforced["approval_required"] = True
        enforced["grounding_status"] = "recovered"
        corrections.append("required_approval_enforced")

    abuse_risk = enforced.get("abuse_risk")
    if isinstance(abuse_risk, dict) and abuse_risk.get("requires_human_review") and not enforced["approval_required"]:
        enforced["approval_required"] = True
        enforced["grounding_status"] = "recovered"
        corrections.append("abuse_review_enforced")
    enforced["risk_review_required"] = bool(isinstance(abuse_risk, dict) and abuse_risk.get("requires_human_review"))

    if (
        not policy.get("requires_approval")
        and not enforced["risk_review_required"]
        and action.get("action_type") == "clarification_request"
        and enforced["approval_required"]
    ):
        enforced["approval_required"] = False
        enforced["grounding_status"] = fallback["grounding_status"]
        corrections.append("unnecessary_approval_removed")

    if action.get("status") != "created":
        enforced["grounding_status"] = "failed"
        corrections.append("action_not_created")

    allowed_actions = policy.get("allowed_actions")
    if isinstance(allowed_actions, list) and action.get("action_type") not in allowed_actions:
        enforced["grounding_status"] = "failed"
        corrections.append("action_not_allowed_by_policy")

    enforced.setdefault("grounding_evidence", _grounding_evidence({}, policy, action))
    enforced.setdefault("allowed_actions", policy.get("allowed_actions", []))
    enforced.setdefault("customer_friendly_resolution", policy.get("customer_friendly_resolution"))

    if corrections:
        enforced["validator_corrections"] = corrections
    return enforced


def _abuse_risk(customer: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    signals: list[str] = []
    prior_refunds = int(customer.get("prior_refunds_12m") or 0)
    chargebacks = int(customer.get("chargeback_count_12m") or 0)
    account_age_days = int(customer.get("account_age_days") or 0)
    payment_verified = bool(customer.get("payment_method_verified", False))
    controls = policy.get("abuse_controls") if isinstance(policy.get("abuse_controls"), dict) else {}
    max_refunds = int(controls.get("max_low_risk_refunds_12m") or 3)

    if prior_refunds > max_refunds:
        signals.append("high_prior_refund_count")
    if chargebacks > 0:
        signals.append("recent_chargebacks")
    if account_age_days and account_age_days < 30:
        signals.append("new_account")
    if customer.get("found") and not payment_verified:
        signals.append("unverified_payment_method")

    level = "low"
    if len(signals) >= 2 or "recent_chargebacks" in signals:
        level = "high"
    elif signals:
        level = "medium"

    return {
        "level": level,
        "signals": signals,
        "requires_human_review": level == "high",
        "principle": controls.get("principle"),
    }


def _approval_reason(validation: dict[str, Any]) -> str:
    if validation.get("risk_review_required"):
        return "Human review required by abuse-risk controls."
    return "Policy requires human approval."


def _grounding_evidence(customer: dict[str, Any], policy: dict[str, Any], action: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    customer_id = customer.get("customer_id") or action.get("customer_id")
    if customer_id:
        evidence.append({"type": "customer", "id": customer_id})
    policy_id = policy.get("policy_id")
    if policy_id:
        evidence.append({"type": "policy", "id": policy_id})
    action_id = action.get("action_id")
    if action_id:
        evidence.append({"type": "action", "id": action_id})
    return evidence


def _mcp_span_data(tool_name: str) -> dict[str, Any]:
    return {"tool_protocol": "mcp", "tool_server": "mcp-tools", "tool_name": tool_name}


PROMPT_VERSION = "support-triage-v1"


def _supervisor_instructions() -> str:
    return (
        "You are the Supervisor Agent in a customer-service multi-agent workflow. "
        "Return only JSON with route and handoff_reason. Route should be triage unless the request is unsafe."
    )


def _triage_instructions() -> str:
    return (
        "You are the Triage Agent. Classify the customer message. Use billing_duplicate_charge only when "
        "the customer reports duplicate or repeated billing. Use stale_subscription_refund for subscription "
        "refund requests tied to old charges. Use consumed_product_return when the customer asks to return "
        "or refund a product they already consumed. Use recent_context to preserve the active issue across "
        "follow-up messages such as order numbers. Return only JSON with issue_type, urgency, sentiment, and "
        "optional missing_information."
    )


def _policy_agent_instructions() -> str:
    return (
        "You are the Policy Agent. Choose the policy retrieval topic for the customer issue. "
        "Do not choose duplicate_charge_refund unless the triage issue is billing_duplicate_charge. "
        "Use consumed_product_return for consumed product return requests. "
        "Return only JSON with retrieval_query and reason."
    )


def _action_agent_instructions() -> str:
    return (
        "You are the Action Agent. Choose the next support action based on customer, policy, "
        "and memory context. Return only JSON with action_type and reason."
    )


def _validator_agent_instructions() -> str:
    return (
        "You are the Validator Agent. Check grounding, policy compliance, abuse-risk signals, and approval needs. "
        "Return only JSON with grounding_status, approval_required, evidence, and optional unsupported_claims."
    )


def _deterministic_decision_response(decision: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        output_text=_json_for_prompt(decision),
        input_tokens=None,
        output_tokens=None,
        estimated_cost=None,
        raw_response={"decision_source": "deterministic"},
    )


def _agent_decision_span_data(response: LLMResponse) -> dict[str, Any]:
    raw_response = response.raw_response or {}
    decision_source = str(raw_response.get("decision_source") or "deterministic")
    span_data = {
        "decision_source": decision_source,
        "prompt_version": PROMPT_VERSION,
    }
    model_metadata = _model_call_span_data(raw_response.get("raw_response") if isinstance(raw_response.get("raw_response"), dict) else raw_response)
    span_data.update(model_metadata)
    fallback_reason = raw_response.get("fallback_reason")
    if fallback_reason:
        span_data["fallback_reason"] = fallback_reason
    validation_reason = raw_response.get("validation_reason")
    if validation_reason:
        span_data["validation_reason"] = validation_reason
    model_output_text = raw_response.get("model_output_text")
    if isinstance(model_output_text, str):
        span_data["model_output_text"] = model_output_text
    return span_data


def _model_call_span_data(raw_response: dict[str, Any] | None) -> dict[str, Any]:
    if not raw_response:
        return {}
    span_data: dict[str, Any] = {}
    model = raw_response.get("agenttrace_model")
    if isinstance(model, str) and model:
        span_data["model"] = model
    attempts = raw_response.get("agenttrace_model_attempts")
    if isinstance(attempts, list):
        span_data["model_attempts"] = attempts
    fallback_used = raw_response.get("agenttrace_model_fallback_used")
    if isinstance(fallback_used, bool):
        span_data["model_fallback_used"] = fallback_used
    return span_data


def _parse_agent_json(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_for_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _customer_response_instructions() -> str:
    return (
        "You are a customer service agent. Write a concise, grounded customer response. "
        "Only mention facts present in the provided customer, policy, action, and validation context. "
        "Do not introduce unrelated account issues, billing flags, duplicate charges, or refunds that are not "
        "part of the customer's current request. "
        "Be customer-friendly: resolve eligible issues, explain approval as a review step when required, "
        "and do not deny solely because human approval is needed. Use the recent conversation history "
        "to answer follow-up questions naturally. Do not repeat first-turn wording like 'I started a review' "
        "when the existing review context is already present."
    )


def _customer_response_input(
    message: str,
    customer: dict[str, Any],
    policy: dict[str, Any],
    action: dict[str, Any],
    validation: dict[str, Any],
    working_memory: dict[str, Any],
    customer_memory: dict[str, Any],
) -> str:
    issue_type = _issue_type_from_working_memory(working_memory)
    return (
        f"Customer message: {message}\n"
        f"Working memory: {working_memory}\n"
        f"Customer context: {_response_customer_context(customer, issue_type)}\n"
        f"Customer memory: {customer_memory}\n"
        f"Policy evidence: {policy}\n"
        f"Support action: {action}\n"
        f"Validation: {validation}"
    )


def _customer_response_safety(
    response_text: str,
    *,
    policy: dict[str, Any],
    action: dict[str, Any],
    working_memory: dict[str, Any],
) -> str:
    if policy.get("policy_id") != "policy_consumed_product_return":
        return response_text

    normalized = response_text.lower()
    agent_state = working_memory.get("agent_state") if isinstance(working_memory.get("agent_state"), dict) else {}
    evidence_ids = agent_state.get("evidence_ids") if isinstance(agent_state, dict) else []
    has_order_evidence = isinstance(evidence_ids, list) and any(str(item).startswith("ord_") for item in evidence_ids)

    additions: list[str] = []
    if action.get("action_type") == "courtesy_credit" and "courtesy credit" not in normalized:
        additions.append("I can review this for a courtesy credit based on the quality issue and order evidence.")
    elif action.get("action_type") == "clarification_request" and has_order_evidence and "normal return" not in normalized:
        additions.append(
            "Because the items were fully consumed, this is not eligible for a normal return, but I can review a quality or safety exception if you share what was wrong."
        )

    if not additions:
        return response_text
    return " ".join([response_text.rstrip(), *additions])


def _static_customer_response(input_text: str, default_response: str) -> str:
    has_conversation_history = _input_has_conversation_history(input_text)
    if "policy_consumed_product_return" in input_text:
        if _has_quality_exception(input_text.lower()):
            return (
                "Thanks for the details. Because this sounds like a quality or safety exception rather than a normal return, "
                "I can review the order for a courtesy credit or escalation with the order evidence."
            )
        if _input_has_order_number(input_text):
            return (
                "Thanks for the order number. Since the bananas were fully consumed, I cannot process a normal return. "
                "If there was a quality, spoilage, safety, or delivery issue, I can review that exception with the order details."
            )
        return (
            "Since the bananas were fully consumed, I cannot process a normal return. If there was a quality, spoilage, "
            "safety, or delivery issue, please share the order number or receipt and what was wrong so I can review it."
        )
    if has_conversation_history and "policy_stale_subscription_refund" in input_text:
        return (
            "For this follow-up, the older-subscription refund review is still waiting for human approval. "
            "I can add any new billing evidence to the review, but I cannot issue the refund before approval."
        )
    if has_conversation_history and "policy_refund_duplicate_charge" in input_text:
        return (
            "For this follow-up, the duplicate-charge review is still based on customer and payment verification. "
            "If you have a receipt or second charge ID, I can attach it to the review."
        )
    if has_conversation_history and "policy_annual_refund" in input_text:
        return (
            "For this follow-up, the annual-plan refund review is still waiting for human approval because of "
            "the refund amount. I can include any new cancellation or billing details in the review."
        )
    if "policy_stale_subscription_refund" in input_text:
        return (
            "I started a refund review for the older subscription charge. Because the charge is older than "
            "the standard self-serve window, it needs human approval before any refund can be issued."
        )
    if "policy_refund_duplicate_charge" in input_text:
        return (
            "I started a refund review for the detected duplicate charge. Duplicate-charge refunds can be "
            "resolved after customer and payment verification."
        )
    if "policy_annual_refund" in input_text:
        return (
            "I started a refund review for the annual plan. Because this is a high-value annual refund, "
            "it needs human approval before execution."
        )
    if "'action_type': 'clarification_request'" in input_text or '"action_type": "clarification_request"' in input_text:
        return "I need one more account or billing detail before I can safely take action on this request."
    return default_response


def _input_has_conversation_history(input_text: str) -> bool:
    empty_markers = (
        "'conversation_history': []",
        '"conversation_history": []',
        "'recent_conversation_turns', 'value': 0",
        '"recent_conversation_turns", "value": 0',
    )
    return "conversation_history" in input_text and not any(marker in input_text for marker in empty_markers)


def _input_has_order_number(input_text: str) -> bool:
    text = input_text.lower()
    return "order number" in text or "order #" in text or "#1234" in text


def _issue_type_from_working_memory(working_memory: dict[str, Any]) -> str:
    facts = working_memory.get("facts")
    if not isinstance(facts, list):
        return "general_support"
    for fact in facts:
        if isinstance(fact, dict) and fact.get("key") == "issue_type":
            return str(fact.get("value") or "general_support")
    return "general_support"


def _response_customer_context(customer: dict[str, Any], issue_type: str) -> dict[str, Any]:
    billing_issue_types = {"billing_duplicate_charge", "annual_plan_refund", "stale_subscription_refund"}
    if issue_type in billing_issue_types:
        return customer
    allowed_keys = {"found", "customer_id", "email", "loyalty_tier", "account_age_days"}
    return {key: value for key, value in customer.items() if key in allowed_keys}


def _rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def _working_memory(
    message: str,
    customer_email: str,
    triage: dict[str, Any],
    conversation_history: list[dict[str, Any]] | None = None,
    agent_state: AgentState | None = None,
) -> dict[str, Any]:
    conversation_history = conversation_history or []
    return {
        "memory_key": f"working:{customer_email}",
        "facts": [
            {"key": "latest_customer_message", "value": message},
            {"key": "issue_type", "value": triage["issue_type"]},
            {"key": "urgency", "value": triage["urgency"]},
            {"key": "recent_conversation_turns", "value": len(conversation_history)},
        ],
        "conversation_history": conversation_history,
        "agent_state": (agent_state or _agent_state(triage=triage)).to_dict(),
    }


def _customer_memory(customer: dict[str, Any], issue_type: str = "general_support") -> dict[str, Any]:
    customer_id = str(customer.get("customer_id") or "unknown")
    if not customer.get("found"):
        memory = {
            "memory_id": "mem_unknown_legacy_note",
            "summary": "Legacy unverified note says the customer may prefer phone support.",
            "source": "support_history",
        }
        return {
            "memories": [memory],
            "relevance_score": 0.42,
            "memory_age_seconds": 86400 * 180,
            "used_in_response": False,
        }
    if issue_type == "consumed_product_return":
        memory = {
            "memory_id": f"mem_{customer_id}_preference",
            "summary": "Customer prefers concise email updates.",
            "source": "support_history",
        }
        return {
            "memories": [memory],
            "relevance_score": 0.72,
            "memory_age_seconds": 86400 * 30,
            "used_in_response": True,
        }
    if customer.get("annual_price_usd", 0) > 500:
        memory = {
            "memory_id": f"mem_{customer_id}_annual_refund",
            "summary": "Prior refund requests on annual plans require careful approval review.",
            "source": "support_history",
        }
        return {
            "memories": [memory],
            "relevance_score": 0.91,
            "memory_age_seconds": 86400 * 12,
            "used_in_response": True,
        }
    memory = {
        "memory_id": f"mem_{customer_id}_billing",
        "summary": "Customer previously contacted support about billing and prefers concise email updates.",
        "source": "support_history",
    }
    return {
        "memories": [memory],
        "relevance_score": 0.82,
        "memory_age_seconds": 86400 * 4,
        "used_in_response": True,
    }
