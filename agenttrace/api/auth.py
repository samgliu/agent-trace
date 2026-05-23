"""Optional single-tenant dashboard authentication."""

from __future__ import annotations

import os
import secrets
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


def auth_config_from_env() -> AuthConfig:
    enabled = os.environ.get("AGENTTRACE_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    return AuthConfig(
        enabled=enabled,
        token=os.environ.get("AGENTTRACE_ADMIN_TOKEN") or os.environ.get("AGENTTRACE_API_TOKEN"),
        cookie_name=os.environ.get("AGENTTRACE_AUTH_COOKIE_NAME", "agenttrace_session"),
        secure_cookie=os.environ.get("AGENTTRACE_AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"},
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
        response.set_cookie(
            config.cookie_name,
            token,
            httponly=True,
            secure=config.secure_cookie,
            samesite="lax",
            path="/",
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
    cookie_token = request.cookies.get(config.cookie_name)
    if isinstance(cookie_token, str) and secrets.compare_digest(cookie_token, config.token):
        return True
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token, config.token)


def _is_public_path(path: str) -> bool:
    return path in {"/health", "/auth/status", "/auth/login", "/auth/logout"}
