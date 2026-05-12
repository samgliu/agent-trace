"""Standalone customer-service agent API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent_apps.customer_service.runner import build_default_runner
from agenttrace.core.models import Trace


class SupportTriageRunRequest(BaseModel):
    message: str
    customer_email: str
    trace_id: str | None = None
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    use_openai: bool = False
    openai_api: Literal["chat_completions", "responses"] = "chat_completions"


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentTrace Customer-Service Agent",
        version="0.1.0",
        description="Standalone customer-service multi-agent runtime.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "customer-service-agent"}

    @app.post("/runs/support-triage")
    def run_support_triage(payload: SupportTriageRunRequest) -> dict[str, Any]:
        try:
            trace = build_default_runner(use_openai=payload.use_openai, openai_api=payload.openai_api).run(
                message=payload.message,
                customer_email=payload.customer_email,
                trace_id=payload.trace_id,
                conversation_history=payload.conversation_history,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"trace": trace.to_dict(), "assistant_response": _assistant_response_from_trace(trace)}

    return app


def _assistant_response_from_trace(trace: Trace) -> str:
    for span in reversed(trace.spans):
        if span.name == "Customer Response Generator" and isinstance(span.output, dict):
            response = span.output.get("response")
            if isinstance(response, str):
                return response
    return ""


app = create_app()

