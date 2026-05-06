"""Support triage multi-agent workflow runner."""

from __future__ import annotations

import os
import uuid
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from agenttrace.core.models import Span, Trace
from agenttrace.core.provenance import with_source_metadata
from agenttrace.mcp_tools.tools import create_support_action, lookup_customer, retrieve_policy

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
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("AGENTTRACE_OPENAI_MODEL", "gpt-5")
        self.base_url = (base_url or os.environ.get("AGENTTRACE_OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip(
            "/"
        )
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIChatCompletionsClient")

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
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("AGENTTRACE_OPENAI_MODEL", "gpt-5")
        self.base_url = (base_url or os.environ.get("AGENTTRACE_OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip(
            "/"
        )
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIResponsesClient")

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
    ) -> None:
        self.llm_client = llm_client or StaticLLMClient()
        self.tools_client = tools_client or LocalSupportToolsClient()

    def run(self, *, message: str, customer_email: str, trace_id: str | None = None) -> Trace:
        trace_id = trace_id or f"trace_support_triage_{uuid.uuid4().hex[:12]}"
        clock = _SpanClock(datetime.now(timezone.utc))
        spans: list[Span] = []
        span_ids = {
            "supervisor": _span_id(trace_id, "supervisor"),
            "handoff_triage": _span_id(trace_id, "handoff_triage"),
            "triage": _span_id(trace_id, "triage"),
            "lookup_customer": _span_id(trace_id, "lookup_customer"),
            "handoff_policy": _span_id(trace_id, "handoff_policy"),
            "policy_agent": _span_id(trace_id, "policy_agent"),
            "retrieve_policy": _span_id(trace_id, "retrieve_policy"),
            "action_agent": _span_id(trace_id, "action_agent"),
            "create_action": _span_id(trace_id, "create_action"),
            "validator": _span_id(trace_id, "validator"),
            "approval_required": _span_id(trace_id, "approval_required"),
            "customer_response": _span_id(trace_id, "customer_response"),
        }

        supervisor = _span(
            trace_id=trace_id,
            span_id=span_ids["supervisor"],
            name="Supervisor Agent",
            span_type="agent",
            clock=clock,
            duration_ms=250,
            input={"message": message, "customer_email": customer_email},
            output={"route": "triage"},
            span_data={"agent_role": "supervisor"},
        )
        spans.append(supervisor)
        spans.append(
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

        triage = _triage(message)
        spans.append(
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
                span_data={"agent_role": "triage"},
            )
        )

        try:
            customer = self.tools_client.lookup_customer(customer_email)
        except Exception as exc:
            spans.append(
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
            )

        spans.append(
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
        spans.append(
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

        policy_topic = _policy_topic(triage, customer)
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=span_ids["policy_agent"],
                name="Policy Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=350,
                input={"topic": policy_topic},
                output={"retrieval_query": policy_topic},
                span_data={"agent_role": "policy"},
            )
        )
        policy = self.tools_client.retrieve_policy(policy_topic)
        spans.append(
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

        action_type = _action_type(triage, customer)
        action_reason = _action_reason(triage, customer, policy)
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=span_ids["action_agent"],
                name="Action Agent",
                span_type="agent",
                parent_id=supervisor.span_id,
                clock=clock,
                duration_ms=450,
                input={"issue_type": triage["issue_type"], "policy": policy},
                output={"action_type": action_type, "reason": action_reason},
                span_data={"agent_role": "action"},
            )
        )
        action = self.tools_client.create_support_action(
            str(customer.get("customer_id") or "unknown"),
            action_type,
            action_reason,
        )
        spans.append(
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
        validation = {
            "grounding_status": "recovered" if requires_approval else "grounded",
            "approval_required": requires_approval,
            "evidence": [customer.get("customer_id"), policy.get("policy_id"), action.get("action_id")],
        }
        spans.append(
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
                span_data={"agent_role": "validator", **validation},
            )
        )
        if requires_approval:
            spans.append(
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
            input_text=_customer_response_input(message, customer, policy, action, validation),
        )
        spans.append(
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
    return SupportTriageRunner(llm_client=llm_client, tools_client=tools_client)


def _trace(
    *,
    trace_id: str,
    status: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    spans: list[Span],
    llm_provider: str,
) -> Trace:
    trace = Trace(
        trace_id=trace_id,
        workflow_name="support-triage",
        status=status,
        metadata={
            "source": "agenttrace-agent-runner",
            "runner": "agenttrace.agents.support_triage",
            "llm_provider": llm_provider,
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


def _action_reason(triage: dict[str, Any], customer: dict[str, Any], policy: dict[str, Any]) -> str:
    return (
        f"{triage['issue_type']} for {customer.get('customer_id', 'unknown customer')} "
        f"under {policy.get('policy_id', 'missing policy')}."
    )


def _mcp_span_data(tool_name: str) -> dict[str, Any]:
    return {"tool_protocol": "mcp", "tool_server": "mcp-tools", "tool_name": tool_name}


def _customer_response_instructions() -> str:
    return (
        "You are a customer service agent. Write a concise, grounded customer response. "
        "Only mention facts present in the provided customer, policy, action, and validation context."
    )


def _customer_response_input(
    message: str,
    customer: dict[str, Any],
    policy: dict[str, Any],
    action: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    return (
        f"Customer message: {message}\n"
        f"Customer context: {customer}\n"
        f"Policy evidence: {policy}\n"
        f"Support action: {action}\n"
        f"Validation: {validation}"
    )


def _rough_token_count(text: str) -> int:
    return max(1, len(text.split()))
