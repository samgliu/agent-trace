"""FastMCP server for AgentTrace demo tools."""

from __future__ import annotations

import argparse

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from agenttrace.mcp_tools.tools import create_support_action, lookup_customer, retrieve_policy

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
def create_support_action_tool(customer_id: str, action_type: str, reason: str) -> dict:
    """Create a support action such as refund review, escalation, or clarification."""
    return create_support_action(customer_id=customer_id, action_type=action_type, reason=reason)


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
