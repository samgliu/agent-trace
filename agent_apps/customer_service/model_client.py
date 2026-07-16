"""Model client abstractions for the customer-service agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

PostJson = Any


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
    fallback_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelCallResult:
    payload: dict[str, Any]
    model: str
    attempts: tuple[dict[str, Any], ...]


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
        self.provider = config.provider
        self.provider_name = f"{config.provider}-chat-completions"
        self.api_key = config.api_key
        self.model = config.model
        self.models = (config.model, *config.fallback_models)
        self.base_url = config.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        if not self.api_key:
            env_prefix = self.provider.upper().replace("-", "_")
            raise RuntimeError(
                f"LLM provider '{self.provider}' is not configured: missing API key. "
                f"Set {env_prefix}_API_KEY or LLM_API_KEY."
            )

        result = _post_with_model_fallback(
            post_json=self._post_json,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            models=self.models,
            path="/chat/completions",
            payload_for_model=lambda model: {
                "model": model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": input_text},
                ],
            },
        )
        payload = result.payload
        usage = payload.get("usage") or {}
        choices = payload.get("choices") or []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        return LLMResponse(
            output_text=str((message or {}).get("content") or ""),
            input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
            output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
            raw_response=_with_model_call_metadata(payload, result),
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
        self.models = (config.model, *config.fallback_models)
        self.base_url = config.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate(self, *, instructions: str, input_text: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("LLM API key is required. Set OPENAI_API_KEY or LLM_API_KEY.")

        result = _post_with_model_fallback(
            post_json=self._post_json,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            models=self.models,
            path="/responses",
            payload_for_model=lambda model: {
                "model": model,
                "reasoning": {"effort": "low"},
                "instructions": instructions,
                "input": input_text,
            },
        )
        payload = result.payload
        usage = payload.get("usage") or {}
        return LLMResponse(
            output_text=str(payload.get("output_text") or ""),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw_response=_with_model_call_metadata(payload, result),
        )


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
        fallback_models=_configured_fallback_models(env_prefix),
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


def _configured_fallback_models(env_prefix: str) -> tuple[str, ...]:
    configured = _first_env(f"{env_prefix}_FALLBACK_MODELS", "LLM_FALLBACK_MODELS", "AGENTTRACE_MODEL_FALLBACKS")
    if not configured:
        return ()
    return tuple(model.strip() for model in configured.split(",") if model.strip())


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


def _post_json(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float) -> dict[str, Any]:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise RuntimeError("httpx is required for OpenAI-compatible LLM clients") from exc
    try:
        response = httpx.post(url, headers=headers, json=json, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(_provider_http_error_message(exc.response.status_code, exc.response.text)) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"LLM provider request failed: {exc}") from exc
    return response.json()


def _post_with_model_fallback(
    *,
    post_json: PostJson,
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    models: tuple[str, ...],
    path: str,
    payload_for_model: Callable[[str], dict[str, Any]],
) -> ModelCallResult:
    last_error: RuntimeError | None = None
    attempts: list[dict[str, Any]] = []
    for model in models:
        try:
            payload = post_json(
                f"{base_url}{path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload_for_model(model),
                timeout=timeout_seconds,
            )
            attempts.append({"model": model, "status": "succeeded"})
            return ModelCallResult(payload=payload, model=model, attempts=tuple(attempts))
        except RuntimeError as exc:
            last_error = exc
            attempts.append({"model": model, "status": "failed", "error": str(exc)})
            if model == models[-1] or not _is_retryable_model_capacity_error(str(exc)):
                raise
    assert last_error is not None
    raise last_error


def _with_model_call_metadata(payload: dict[str, Any], result: ModelCallResult) -> dict[str, Any]:
    return {
        **payload,
        "agenttrace_model": result.model,
        "agenttrace_model_attempts": list(result.attempts),
        "agenttrace_model_fallback_used": len(result.attempts) > 1,
    }


def _is_retryable_model_capacity_error(message: str) -> bool:
    retryable_markers = ("HTTP 429", "HTTP 503", "HTTP 529", "RESOURCE_EXHAUSTED", "UNAVAILABLE")
    return any(marker in message for marker in retryable_markers)


def _provider_http_error_message(status_code: int, response_text: str) -> str:
    detail = _provider_error_detail(response_text)
    if detail:
        return f"LLM provider request failed with HTTP {status_code}: {detail}"
    return f"LLM provider request failed with HTTP {status_code}."


def _provider_error_detail(response_text: str) -> str | None:
    if not response_text:
        return None
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("status") or error.get("code")
        if message:
            return str(message)[:500]
    if isinstance(error, str):
        return error[:500]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if detail:
        return str(detail)[:500]
    return response_text[:500]
