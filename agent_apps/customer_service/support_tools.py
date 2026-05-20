"""Support tool client implementations for the customer-service agent."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable

from agent_apps.customer_service.domain import (
    create_quality_exception_review,
    create_refund_review,
    create_support_action,
    lookup_charge,
    lookup_customer,
    lookup_order,
    lookup_subscription,
    retrieve_policy,
    verify_account_access,
    verify_order_owner,
)

AsyncToolCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class SupportToolsClient:
    def lookup_customer(self, email: str) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_policy(self, topic: str) -> dict[str, Any]:
        raise NotImplementedError

    def lookup_order(self, order_number: str) -> dict[str, Any]:
        raise NotImplementedError

    def lookup_charge(self, customer_id: str, charge_id: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def lookup_subscription(self, customer_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def verify_order_owner(self, order_number: str, customer_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def verify_account_access(self, customer_id: str, requested_account_hint: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_refund_review(
        self,
        customer_id: str,
        policy_id: str,
        reason: str,
        amount_usd: int | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def create_quality_exception_review(
        self,
        customer_id: str,
        order_id: str,
        reason: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class LocalSupportToolsClient(SupportToolsClient):
    def lookup_customer(self, email: str) -> dict[str, Any]:
        return lookup_customer(email)

    def retrieve_policy(self, topic: str) -> dict[str, Any]:
        return retrieve_policy(topic)

    def lookup_order(self, order_number: str) -> dict[str, Any]:
        return lookup_order(order_number)

    def lookup_charge(self, customer_id: str, charge_id: str | None = None) -> dict[str, Any]:
        return lookup_charge(customer_id=customer_id, charge_id=charge_id)

    def lookup_subscription(self, customer_id: str) -> dict[str, Any]:
        return lookup_subscription(customer_id=customer_id)

    def verify_order_owner(self, order_number: str, customer_id: str) -> dict[str, Any]:
        return verify_order_owner(order_number=order_number, customer_id=customer_id)

    def verify_account_access(self, customer_id: str, requested_account_hint: str | None = None) -> dict[str, Any]:
        return verify_account_access(customer_id=customer_id, requested_account_hint=requested_account_hint)

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
        return create_support_action(customer_id, action_type, reason)

    def create_refund_review(
        self,
        customer_id: str,
        policy_id: str,
        reason: str,
        amount_usd: int | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return create_refund_review(customer_id, policy_id, reason, amount_usd, evidence_ids)

    def create_quality_exception_review(
        self,
        customer_id: str,
        order_id: str,
        reason: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return create_quality_exception_review(customer_id, order_id, reason, evidence_ids)


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
        return _mcp_tool_result(_run_async_tool(self._call_tool("lookup_customer_tool", {"email": email})))

    def retrieve_policy(self, topic: str) -> dict[str, Any]:
        return _mcp_tool_result(_run_async_tool(self._call_tool("retrieve_policy_tool", {"topic": topic})))

    def lookup_order(self, order_number: str) -> dict[str, Any]:
        return _mcp_tool_result(_run_async_tool(self._call_tool("lookup_order_tool", {"order_number": order_number})))

    def lookup_charge(self, customer_id: str, charge_id: str | None = None) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(self._call_tool("lookup_charge_tool", {"customer_id": customer_id, "charge_id": charge_id}))
        )

    def lookup_subscription(self, customer_id: str) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(self._call_tool("lookup_subscription_tool", {"customer_id": customer_id}))
        )

    def verify_order_owner(self, order_number: str, customer_id: str) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(
                self._call_tool("verify_order_owner_tool", {"order_number": order_number, "customer_id": customer_id})
            )
        )

    def verify_account_access(self, customer_id: str, requested_account_hint: str | None = None) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(
                self._call_tool(
                    "verify_account_access_tool",
                    {"customer_id": customer_id, "requested_account_hint": requested_account_hint},
                )
            )
        )

    def create_support_action(self, customer_id: str, action_type: str, reason: str) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(
                self._call_tool(
                    "create_support_action_tool",
                    {
                        "customer_id": customer_id,
                        "action_type": action_type,
                        "reason": reason,
                    },
                )
            )
        )

    def create_refund_review(
        self,
        customer_id: str,
        policy_id: str,
        reason: str,
        amount_usd: int | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(
                self._call_tool(
                    "create_refund_review_tool",
                    {
                        "customer_id": customer_id,
                        "policy_id": policy_id,
                        "reason": reason,
                        "amount_usd": amount_usd,
                        "evidence_ids": evidence_ids,
                    },
                )
            )
        )

    def create_quality_exception_review(
        self,
        customer_id: str,
        order_id: str,
        reason: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return _mcp_tool_result(
            _run_async_tool(
                self._call_tool(
                    "create_quality_exception_review_tool",
                    {
                        "customer_id": customer_id,
                        "order_id": order_id,
                        "reason": reason,
                        "evidence_ids": evidence_ids,
                    },
                )
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


def _run_async_tool(awaitable: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("McpSupportToolsClient cannot run inside an active event loop")


def _mcp_tool_result(data: dict[str, Any]) -> dict[str, Any]:
    error = data.get("error")
    if data.get("ok") is False and isinstance(error, dict):
        error_type = str(error.get("type") or "RuntimeError")
        message = str(error.get("message") or "MCP tool failed.")
        if error_type == "TimeoutError":
            raise TimeoutError(message)
        if error_type == "ValueError":
            raise ValueError(message)
        raise RuntimeError(message)
    return data
