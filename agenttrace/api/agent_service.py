"""Client for running the customer-service agent from the API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from agent_apps.customer_service.runner import build_default_runner
from agenttrace.core.models import Trace


class AgentServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def run_support_triage_agent(
    *,
    message: str,
    customer_email: str,
    trace_id: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    use_openai: bool = False,
    openai_api: str = "chat_completions",
) -> Trace:
    agent_service_url = _agent_service_url()
    if agent_service_url:
        return _run_support_triage_via_agent_service(
            agent_service_url=agent_service_url,
            message=message,
            customer_email=customer_email,
            trace_id=trace_id,
            conversation_history=conversation_history or [],
            use_openai=use_openai,
            openai_api=openai_api,
        )
    return build_default_runner(use_openai=use_openai, openai_api=openai_api).run(
        message=message,
        customer_email=customer_email,
        trace_id=trace_id,
        conversation_history=conversation_history,
    )


def _agent_service_url() -> str | None:
    raw_value = os.environ.get("AGENTTRACE_AGENT_SERVICE_URL", "").strip()
    return raw_value.rstrip("/") if raw_value else None


def _run_support_triage_via_agent_service(
    *,
    agent_service_url: str,
    message: str,
    customer_email: str,
    trace_id: str | None,
    conversation_history: list[dict[str, Any]],
    use_openai: bool,
    openai_api: str,
) -> Trace:
    payload = {
        "message": message,
        "customer_email": customer_email,
        "trace_id": trace_id,
        "conversation_history": conversation_history,
        "use_openai": use_openai,
        "openai_api": openai_api,
    }
    response = _post_agent_service_json(f"{agent_service_url}/runs/support-triage", payload)
    trace_payload = response.get("trace")
    if not isinstance(trace_payload, dict):
        raise AgentServiceError("Agent service returned an invalid trace payload.", status_code=502)
    return Trace.from_dict(trace_payload)


def _post_agent_service_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_agent_service_timeout_seconds()) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = _agent_service_error_message(exc)
        raise AgentServiceError(message, status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise AgentServiceError(f"Agent service is unavailable: {exc.reason}", status_code=502) from exc
    except TimeoutError as exc:
        raise AgentServiceError("Agent service timed out while running the workflow.", status_code=504) from exc
    if not isinstance(parsed, dict):
        raise AgentServiceError("Agent service returned an invalid JSON payload.", status_code=502)
    return parsed


def _agent_service_timeout_seconds() -> float:
    raw_value = os.environ.get("AGENTTRACE_AGENT_SERVICE_TIMEOUT_SECONDS", "300")
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return 300.0


def _agent_service_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return f"Agent service request failed with HTTP {exc.code}."
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    return f"Agent service request failed with HTTP {exc.code}."
