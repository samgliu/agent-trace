"""Default customer-service runner factory."""

from __future__ import annotations

import os

from agent_apps.customer_service.model_client import LLMClient, OpenAIChatCompletionsClient, OpenAIResponsesClient
from agent_apps.customer_service.runner import SupportTriageRunner
from agent_apps.customer_service.static_llm import StaticLLMClient
from agent_apps.customer_service.support_tools import LocalSupportToolsClient, McpSupportToolsClient, SupportToolsClient


def build_default_runner(*, use_openai: bool = False, openai_api: str = "chat_completions") -> SupportTriageRunner:
    if not use_openai:
        llm_client: LLMClient = StaticLLMClient()
    elif openai_api == "responses":
        llm_client = OpenAIResponsesClient(timeout_seconds=llm_timeout_seconds())
    else:
        llm_client = OpenAIChatCompletionsClient(timeout_seconds=llm_timeout_seconds())

    tools_client: SupportToolsClient
    if os.environ.get("AGENTTRACE_MCP_TOOLS_URL"):
        tools_client = McpSupportToolsClient()
    else:
        tools_client = LocalSupportToolsClient()
    return SupportTriageRunner(llm_client=llm_client, tools_client=tools_client, use_llm_agents=use_openai)


def llm_timeout_seconds() -> float:
    raw_value = os.environ.get("AGENTTRACE_LLM_TIMEOUT_SECONDS", "180")
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return 180.0
