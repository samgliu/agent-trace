"""Deterministic LLM client used by tests and local demos."""

from __future__ import annotations

from agent_apps.customer_service.model_client import LLMClient, LLMResponse
from agent_apps.customer_service.response_generation import rough_token_count, static_customer_response


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
            output_text = static_customer_response(input_text, self.output_text)
        return LLMResponse(
            output_text=output_text,
            input_tokens=rough_token_count(instructions + "\n" + input_text),
            output_tokens=rough_token_count(output_text),
            estimated_cost=0.0,
            raw_response={"provider": self.provider_name},
        )
