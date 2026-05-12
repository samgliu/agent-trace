"""FastMCP server for AgentTrace demo tools."""

from __future__ import annotations

import argparse

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from agenttrace.mcp_tools.tools import (
    create_quality_exception_review,
    create_refund_review,
    create_support_action,
    lookup_charge,
    lookup_customer,
    lookup_order,
    retrieve_policy,
    verify_order_owner,
)

mcp = FastMCP(
    name="support-tools-mcp",
    instructions="Customer support tools for AgentTrace support-triage workflows.",
)


@mcp.tool
def lookup_customer_tool(email: str) -> dict:
    """Look up customer account context by email."""
    return lookup_customer(email)


@mcp.tool
def retrieve_policy_tool(topic: str) -> dict:
    """Retrieve support policy evidence by topic."""
    return retrieve_policy(topic)


@mcp.tool
def lookup_order_tool(order_number: str) -> dict:
    """Look up order evidence by order number."""
    return lookup_order(order_number)


@mcp.tool
def lookup_charge_tool(customer_id: str, charge_id: str | None = None) -> dict:
    """Look up charge evidence by customer and optional charge ID."""
    return lookup_charge(customer_id=customer_id, charge_id=charge_id)


@mcp.tool
def verify_order_owner_tool(order_number: str, customer_id: str) -> dict:
    """Verify that an order belongs to a customer."""
    return verify_order_owner(order_number=order_number, customer_id=customer_id)


@mcp.tool
def create_support_action_tool(customer_id: str, action_type: str, reason: str) -> dict:
    """Create a support action such as refund review, escalation, or clarification."""
    return create_support_action(customer_id=customer_id, action_type=action_type, reason=reason)


@mcp.tool
def create_refund_review_tool(
    customer_id: str,
    policy_id: str,
    reason: str,
    amount_usd: int | None = None,
    evidence_ids: list[str] | None = None,
) -> dict:
    """Create a refund review with linked policy and evidence."""
    return create_refund_review(
        customer_id=customer_id,
        policy_id=policy_id,
        reason=reason,
        amount_usd=amount_usd,
        evidence_ids=evidence_ids,
    )


@mcp.tool
def create_quality_exception_review_tool(
    customer_id: str,
    order_id: str,
    reason: str,
    evidence_ids: list[str] | None = None,
) -> dict:
    """Create a quality/safety exception review for a consumed product."""
    return create_quality_exception_review(
        customer_id=customer_id,
        order_id=order_id,
        reason=reason,
        evidence_ids=evidence_ids,
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AgentTrace FastMCP tools server.")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
