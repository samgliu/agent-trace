"""Support triage multi-agent workflow runner."""

from __future__ import annotations

import os
import uuid
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agenttrace.mcp_tools.tools import VALID_ACTIONS, create_support_action, lookup_customer, retrieve_policy

PostJson = Any
AsyncToolCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class LLMResponse:
    output_text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    raw_response: dict[str, Any] | None = None


class LLMClient:
    provider_name = "unknown"

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        raise NotImplementedError


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    api_key: str | None
    model: str
    base_url: str


class StaticLLMClient(LLMClient):
    provider_name = "static"

    def __init__(self, output_text: str | None = None) -> None:
        self.output_text = output_text or (
            "Thanks for the details. I reviewed the account and policy context, "
            "and created the next support action for review."
        )

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        return LLMResponse(
            output_text=self.output_text,
            input_tokens=_rough_token_count(instructions + "\n" + input_text),
            output_tokens=_rough_token_count(self.output_text),
            estimated_cost=0.0,
            raw_response={"provider": self.provider_name},
        )


class OpenAIChatCompletionsClient(LLMClient):
    provider_name = "openai-compatible-chat-completions"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        post_json: PostJson | None = None,
    ) -> None:
        config = resolve_model_config(api_key=api_key, model=model, base_url=base_url)
        self.provider_name = f"{config.provider}-chat-completions"
        self.api_key = config.api_key
        self.model = config.model
        self.base_url = config.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("LLM API key is required. Set the provider-specific API key or LLM_API_KEY.")

        payload = self._post_json(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": input_text},
                ],
            },
            timeout=self.timeout_seconds,
        )
        usage = payload.get("usage") or {}
        choices = payload.get("choices") or []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        return LLMResponse(
            output_text=str((message or {}).get("content") or ""),
            input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
            output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
            raw_response=payload,
        )


class OpenAIResponsesClient(LLMClient):
    provider_name = "openai-responses"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        post_json: PostJson | None = None,
    ) -> None:
        config = resolve_model_config(api_key=api_key, model=model, base_url=base_url, default_provider="openai")
        self.provider_name = f"{config.provider}-responses"
        self.api_key = config.api_key
        self.model = config.model
        self.base_url = config.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("LLM API key is required. Set OPENAI_API_KEY or LLM_API_KEY.")

        payload = self._post_json(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "reasoning": {"effort": "low"},
                "instructions": instructions,
                "input": input_text,
            },
            timeout=self.timeout_seconds,
        )
        usage = payload.get("usage") or {}
        return LLMResponse(
            output_text=str(payload.get("output_text") or ""),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw_response=payload,
        )


class SupportToolsClient:
    def lookup_customer(self, email: str) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_policy(self, topic: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
        raise NotImplementedError


class LocalSupportToolsClient(SupportToolsClient):
    def lookup_customer(self, email: str) -> dict[str, Any]:
        return lookup_customer(email)

    def retrieve_policy(self, topic: str) -> dict[str, Any]:
        return retrieve_policy(topic)

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
        return create_support_action(customer_id, action_type, reason)


class McpSupportToolsClient(SupportToolsClient):
    def __init__(
        self,
        *,
        server_url: str | None = None,
        timeout_seconds: float = 10.0,
        call_tool: AsyncToolCall | None = None,
    ) -> None:
        self.server_url = server_url or os.environ.get("AGENTTRACE_MCP_TOOLS_URL") or "http://localhost:8010/mcp/"
        self.timeout_seconds = timeout_seconds
        self._call_tool = call_tool or self._call_fastmcp_tool

    def lookup_customer(self, email: str) -> dict[str, Any]:
        return _run_async_tool(self._call_tool("lookup_customer_tool", {"email": email}))

    def retrieve_policy(self, topic: str) -> dict[str, Any]:
        return _run_async_tool(self._call_tool("retrieve_policy_tool", {"topic": topic}))

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
        return _run_async_tool(
            self._call_tool(
                "create_support_action_tool",
                {
                    "customer_id": customer_id,
                    "action_type": action_type,
                    "reason": reason,
                },
            )
        )

    async def _call_fastmcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            from fastmcp import Client
        except ModuleNotFoundError as exc:
            raise RuntimeError("fastmcp is required for McpSupportToolsClient") from exc

        async with Client(self.server_url, timeout=self.timeout_seconds) as client:
            result = await client.call_tool(tool_name, arguments)
        data = getattr(result, "data", None) or getattr(result, "structured_content", None)
        if not isinstance(data, dict):
            raise RuntimeError(f"MCP tool returned unsupported payload for {tool_name}")
        return data


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
        on_span: Callable[[Span], None] | None = None,
    ) -> Trace:
        trace_id = trace_id or f"trace_support_triage_{uuid.uuid4().hex[:12]}"
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
            "handoff_policy": _span_id(trace_id, "handoff_policy"),
            "policy_agent": _span_id(trace_id, "policy_agent"),
            "retrieve_policy": _span_id(trace_id, "retrieve_policy"),
            "customer_memory_read": _span_id(trace_id, "customer_memory_read"),
            "action_agent": _span_id(trace_id, "action_agent"),
            "create_action": _span_id(trace_id, "create_action"),
            "validator": _span_id(trace_id, "validator"),
            "approval_required": _span_id(trace_id, "approval_required"),
            "customer_response": _span_id(trace_id, "customer_response"),
        }

        supervisor_decision, supervisor_llm = self._agent_decision(
            agent_name="Supervisor Agent",
            instructions=_supervisor_instructions(),
            input_data={"message": message, "customer_email": customer_email},
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
            input={"message": message, "customer_email": customer_email},
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

        triage, triage_llm = self._agent_decision(
            agent_name="Triage Agent",
            instructions=_triage_instructions(),
            input_data={"message": message},
            fallback=_triage(message),
            allowed_keys={"issue_type", "urgency", "sentiment", "missing_information"},
        )
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["triage"],
                name="Triage Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=400,
                input={"message": message},
                output=triage,
                span_data={
                    "agent_role": "triage",
                    "model_provider": self.llm_client.provider_name,
                    **_agent_decision_span_data(triage_llm),
                },
                input_tokens=triage_llm.input_tokens,
                output_tokens=triage_llm.output_tokens,
                estimated_cost=triage_llm.estimated_cost,
            )
        )
        working_memory = _working_memory(message, customer_email, triage)
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
        policy_topic = str(policy_plan.get("retrieval_query") or _policy_topic(triage, customer))
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
        customer_memory = _customer_memory(customer)
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

        fallback_action = {
            "action_type": _action_type(triage, customer),
            "reason": _action_reason(triage, customer, policy, customer_memory),
        }
        action_decision, action_llm = self._agent_decision(
            agent_name="Action Agent",
            instructions=_action_agent_instructions(),
            input_data={"triage": triage, "customer": customer, "policy": policy, "memory": customer_memory},
            fallback=fallback_action,
            allowed_keys={"action_type", "reason"},
        )
        action_type = str(action_decision.get("action_type") or fallback_action["action_type"])
        action_reason = str(action_decision.get("reason") or fallback_action["reason"])
        action_safety = _action_safety(action_type, policy)
        if action_safety:
            action_type = fallback_action["action_type"]
            action_reason = fallback_action["reason"]
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["action_agent"],
                name="Action Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=450,
                input={"issue_type": triage["issue_type"], "policy": policy, "memory": customer_memory},
                output={"action_type": action_type, "reason": action_reason},
                span_data={
                    "agent_role": "action",
                    "model_provider": self.llm_client.provider_name,
                    **_agent_decision_span_data(action_llm),
                    **action_safety,
                },
                input_tokens=action_llm.input_tokens,
                output_tokens=action_llm.output_tokens,
                estimated_cost=action_llm.estimated_cost,
            )
        )
        action = self.tools_client.create_support_action(
            str(customer.get("customer_id") or "unknown"),
            action_type,
            action_reason,
        )
        emit(
            _span(
                trace_id=trace_id,
                span_id=span_ids["create_action"],
                name="create_support_action",
                span_type="function_tool",
                parent_id=span_ids["action_agent"],
                clock=clock,
                duration_ms=150,
                input={"customer_id": customer.get("customer_id"), "action_type": action_type, "reason": action_reason},
                output=action,
                span_data=_mcp_span_data("create_support_action_tool"),
            )
        )

        requires_approval = bool(policy.get("requires_approval"))
        validation_fallback = {
            "grounding_status": "recovered" if requires_approval else "grounded",
            "approval_required": requires_approval,
            "evidence": [customer.get("customer_id"), policy.get("policy_id"), action.get("action_id")],
            "grounding_evidence": _grounding_evidence(customer, policy, action),
            "allowed_actions": policy.get("allowed_actions", []),
            "customer_friendly_resolution": policy.get("customer_friendly_resolution"),
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
                    output={"approval_status": "blocked", "reason": "Policy requires human approval."},
                    span_data={
                        "approval_required": True,
                        "approval_status": "blocked",
                        "policy_id": policy.get("policy_id"),
                        "action_id": action.get("action_id"),
                    },
                )
            )

        llm_response = self.llm_client.generate(
            instructions=_customer_response_instructions(),
            input_text=_customer_response_input(message, customer, policy, action, validation, working_memory, customer_memory),
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
                output={"response": llm_response.output_text},
                span_data={"model_provider": self.llm_client.provider_name, "raw_response": llm_response.raw_response},
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                estimated_cost=llm_response.estimated_cost,
            )
        )

        return _trace(
            trace_id=trace_id,
            status="recovered" if requires_approval else "passed",
            started_at=spans[0].started_at,
            ended_at=spans[-1].ended_at,
            spans=spans,
            llm_provider=self.llm_client.provider_name,
            agent_decision_mode="llm" if self.use_llm_agents else "deterministic",
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
        llm_client = OpenAIResponsesClient()
    else:
        llm_client = OpenAIChatCompletionsClient()
    tools_client: SupportToolsClient
    if os.environ.get("AGENTTRACE_MCP_TOOLS_URL"):
        tools_client = McpSupportToolsClient()
    else:
        tools_client = LocalSupportToolsClient()
    return SupportTriageRunner(llm_client=llm_client, tools_client=tools_client, use_llm_agents=use_openai)


def resolve_model_config(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    default_provider: str | None = None,
) -> ModelConfig:
    provider = _configured_provider(default_provider)
    env_prefix = provider.upper().replace("-", "_")
    return ModelConfig(
        provider=provider,
        api_key=api_key or _first_env(f"{env_prefix}_API_KEY", "LLM_API_KEY", "AGENTTRACE_MODEL_API_KEY", "OPENAI_API_KEY"),
        model=model or _configured_model(env_prefix, provider),
        base_url=base_url or _configured_base_url(env_prefix, provider),
    )


def _configured_provider(default_provider: str | None) -> str:
    provider = os.environ.get("LLM_PROVIDER") or os.environ.get("AGENTTRACE_LLM_PROVIDER") or default_provider or "openai"
    return provider.strip().lower().replace("_", "-")


def _configured_model(env_prefix: str, provider: str) -> str:
    configured = _first_env(f"{env_prefix}_MODEL", "LLM_MODEL", "AGENTTRACE_MODEL_NAME", "AGENTTRACE_OPENAI_MODEL", "OPENAI_MODEL")
    if configured:
        return configured
    defaults = {
        "openai": "gpt-5",
        "openai-compatible": "gpt-5",
        "gemini": "gemini-2.5-flash",
        "local": "local-model",
    }
    return defaults.get(provider, "gpt-5")


def _configured_base_url(env_prefix: str, provider: str) -> str:
    configured = _first_env(f"{env_prefix}_BASE_URL", "LLM_BASE_URL", "AGENTTRACE_MODEL_BASE_URL", "AGENTTRACE_OPENAI_BASE_URL")
    if configured:
        return configured
    defaults = {
        "openai": "https://api.openai.com/v1",
        "openai-compatible": "https://api.openai.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        "local": "http://localhost:8001/v1",
    }
    return defaults.get(provider, "https://api.openai.com/v1")


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _trace(
    *,
    trace_id: str,
    status: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    spans: list[Span],
    llm_provider: str,
    agent_decision_mode: str,
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
        },
        raw_payload=None,
        started_at=started_at,
        ended_at=ended_at,
        spans=spans,
    )
    return with_source_metadata(trace, source_format="agenttrace", source_kind="agent_runner")


def _post_json(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> dict[str, Any]:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise RuntimeError("httpx is required for OpenAI-compatible LLM clients") from exc
    response = httpx.post(url, headers=headers, json=json, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _run_async_tool(awaitable: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("McpSupportToolsClient cannot run inside an active event loop")


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


def _triage(message: str) -> dict[str, Any]:
    text = message.lower()
    if "charged twice" in text or "duplicate" in text:
        issue_type = "billing_duplicate_charge"
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
    return {"issue_type": issue_type, "urgency": urgency, "sentiment": "concerned"}


def _policy_topic(triage: dict[str, Any], customer: dict[str, Any]) -> str:
    if triage["issue_type"] == "annual_plan_refund" or customer.get("annual_price_usd", 0) > 500:
        return "annual_plan_refund"
    if triage["issue_type"] == "billing_duplicate_charge":
        return "duplicate_charge_refund"
    return "duplicate_charge_refund"


def _action_type(triage: dict[str, Any], customer: dict[str, Any]) -> str:
    if not customer.get("found"):
        return "clarification_request"
    if triage["issue_type"] == "account_access":
        return "escalation"
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


def _action_safety(action_type: str, policy: dict[str, Any]) -> dict[str, Any]:
    normalized_action = action_type.strip().lower()
    if normalized_action not in VALID_ACTIONS:
        return {
            "decision_source": "fallback",
            "fallback_reason": "unsupported_action_type",
            "rejected_action_type": action_type,
        }
    allowed_actions = policy.get("allowed_actions")
    if not isinstance(allowed_actions, list) or normalized_action in allowed_actions:
        return {}
    return {
        "decision_source": "fallback",
        "fallback_reason": "action_not_allowed_by_policy",
        "rejected_action_type": action_type,
        "policy_allowed_actions": allowed_actions,
    }


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
        "You are the Triage Agent. Classify the customer message. Return only JSON with "
        "issue_type, urgency, sentiment, and optional missing_information."
    )


def _policy_agent_instructions() -> str:
    return (
        "You are the Policy Agent. Choose the policy retrieval topic for the customer issue. "
        "Return only JSON with retrieval_query and reason."
    )


def _action_agent_instructions() -> str:
    return (
        "You are the Action Agent. Choose the next support action based on customer, policy, "
        "and memory context. Return only JSON with action_type and reason."
    )


def _validator_agent_instructions() -> str:
    return (
        "You are the Validator Agent. Check grounding, policy compliance, and approval needs. "
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
    fallback_reason = raw_response.get("fallback_reason")
    if fallback_reason:
        span_data["fallback_reason"] = fallback_reason
    model_output_text = raw_response.get("model_output_text")
    if isinstance(model_output_text, str):
        span_data["model_output_text"] = model_output_text
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
        "Be customer-friendly: resolve eligible issues, explain approval as a review step when required, "
        "and do not deny solely because human approval is needed."
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
    return (
        f"Customer message: {message}\n"
        f"Working memory: {working_memory}\n"
        f"Customer context: {customer}\n"
        f"Customer memory: {customer_memory}\n"
        f"Policy evidence: {policy}\n"
        f"Support action: {action}\n"
        f"Validation: {validation}"
    )


def _rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def _working_memory(message: str, customer_email: str, triage: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_key": f"working:{customer_email}",
        "facts": [
            {"key": "latest_customer_message", "value": message},
            {"key": "issue_type", "value": triage["issue_type"]},
            {"key": "urgency", "value": triage["urgency"]},
        ],
    }


def _customer_memory(customer: dict[str, Any]) -> dict[str, Any]:
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
