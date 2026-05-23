"""Optional single-tenant dashboard authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    token: str | None
    cookie_name: str = "agenttrace_session"
    secure_cookie: bool = False
    session_ttl_seconds: int = 28800


def auth_config_from_env() -> AuthConfig:
    enabled = os.environ.get("AGENTTRACE_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    return AuthConfig(
        enabled=enabled,
        token=os.environ.get("AGENTTRACE_ADMIN_TOKEN") or os.environ.get("AGENTTRACE_API_TOKEN"),
        cookie_name=os.environ.get("AGENTTRACE_AUTH_COOKIE_NAME", "agenttrace_session"),
        secure_cookie=os.environ.get("AGENTTRACE_AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"},
        session_ttl_seconds=_env_int("AGENTTRACE_AUTH_SESSION_TTL_SECONDS", 28800),
    )


def register_auth(app: FastAPI, config: AuthConfig) -> None:
    @app.middleware("http")
    async def require_auth(request: Request, call_next: Any) -> Response:
        if request.method == "OPTIONS" or _is_public_path(request.url.path):
            return await call_next(request)
        if is_authenticated(request, config):
            return await call_next(request)
        return JSONResponse({"detail": "Authentication required."}, status_code=401)

    @app.get("/auth/status")
    def auth_status(request: Request) -> dict[str, bool]:
        return {
            "enabled": config.enabled,
            "authenticated": is_authenticated(request, config),
        }

    @app.post("/auth/login")
    async def auth_login(request: Request, response: Response) -> dict[str, bool]:
        if not config.enabled:
            return {"authenticated": True}
        if not config.token:
            raise HTTPException(status_code=500, detail="Authentication is enabled but no admin token is configured.")
        payload = await request.json()
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not secrets.compare_digest(token, config.token):
            raise HTTPException(status_code=401, detail="Invalid access token.")
        session_token = _create_session_token(config)
        response.set_cookie(
            config.cookie_name,
            session_token,
            httponly=True,
            secure=config.secure_cookie,
            samesite="lax",
            path="/",
            max_age=config.session_ttl_seconds,
        )
        return {"authenticated": True}

    @app.post("/auth/logout")
    def auth_logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(config.cookie_name, path="/")
        return {"authenticated": False}


def is_authenticated(request: Request, config: AuthConfig) -> bool:
    if not config.enabled:
        return True
    if not config.token:
        return False
    cookie_value = request.cookies.get(config.cookie_name)
    if isinstance(cookie_value, str) and _verify_session_token(cookie_value, config):
        return True
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token, config.token)


def _is_public_path(path: str) -> bool:
    return path in {"/health", "/auth/status", "/auth/login", "/auth/logout"}


def _create_session_token(config: AuthConfig) -> str:
    payload = {
        "exp": int(time.time()) + config.session_ttl_seconds,
        "nonce": secrets.token_urlsafe(16),
    }
    encoded_payload = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded_payload, config)
    return f"{encoded_payload}.{signature}"


def _verify_session_token(session_token: str, config: AuthConfig) -> bool:
    encoded_payload, separator, signature = session_token.partition(".")
    if not separator or not encoded_payload or not signature:
        return False
    if not secrets.compare_digest(signature, _sign(encoded_payload, config)):
        return False
    try:
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError):
        return False
    expires_at = payload.get("exp") if isinstance(payload, dict) else None
    return isinstance(expires_at, int) and expires_at > int(time.time())


def _sign(encoded_payload: str, config: AuthConfig) -> str:
    secret = (config.token or "").encode("utf-8")
    digest = hmac.new(secret, encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    return _base64url_encode(digest)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default
