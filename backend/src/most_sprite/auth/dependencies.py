from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from most_sprite.config import get_settings
from most_sprite.domain.enums import Role
from most_sprite.domain.schemas import CurrentUser
from most_sprite.errors import SpriteError

bearer = HTTPBearer(auto_error=False)
_jwks_clients: dict[str, PyJWKClient] = {}


def _dev_identity(x_sprite_user: str | None, x_sprite_role: str | None) -> CurrentUser:
    try:
        role = Role(x_sprite_role or Role.OBSERVER)
    except ValueError as exc:
        raise SpriteError("INVALID_ROLE", "unknown development role", status_code=403) from exc
    subject = (x_sprite_user or "local-observer").strip()
    return CurrentUser(subject=subject, display_name=subject, role=role, auth_mode="dev")


async def _oidc_identity(token: str) -> CurrentUser:
    settings = get_settings()
    assert settings.oidc_issuer and settings.oidc_audience
    discovery_url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            discovery: dict[str, Any] = response.json()
        jwks_uri = str(discovery["jwks_uri"])
        jwks = _jwks_clients.setdefault(jwks_uri, PyJWKClient(jwks_uri))
        signing_key = await asyncio.to_thread(jwks.get_signing_key_from_jwt, token)
        supported = discovery.get("id_token_signing_alg_values_supported", ["RS256", "ES256"])
        allowed_algorithms = [value for value in supported if value in {"RS256", "ES256"}]
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=allowed_algorithms,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except (httpx.HTTPError, KeyError, ValueError, jwt.PyJWTError) as exc:
        raise SpriteError(
            "AUTH_TOKEN_INVALID",
            "OIDC token validation failed",
            status_code=401,
            details={"reason": type(exc).__name__},
        ) from exc
    roles = claims.get("sprite_roles") or claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    matched = next((Role(value) for value in roles if value in Role._value2member_map_), None)
    if matched is None:
        raise SpriteError("ROLE_REQUIRED", "token has no MOST-SPRITE role", status_code=403)
    return CurrentUser(
        subject=claims["sub"],
        display_name=claims.get("name", claims["sub"]),
        role=matched,
        auth_mode="oidc",
    )


async def authenticate_identity(
    *, token: str | None, x_sprite_user: str | None, x_sprite_role: str | None
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode == "dev":
        if settings.app_env == "production":
            raise SpriteError("AUTH_MISCONFIGURED", "development auth is disabled", status_code=503)
        return _dev_identity(x_sprite_user, x_sprite_role)
    if not token:
        raise SpriteError("AUTH_REQUIRED", "bearer token required", status_code=401)
    return await _oidc_identity(token)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_sprite_user: str | None = Header(default=None),
    x_sprite_role: str | None = Header(default=None),
) -> CurrentUser:
    return await authenticate_identity(
        token=credentials.credentials if credentials else None,
        x_sprite_user=x_sprite_user,
        x_sprite_role=x_sprite_role,
    )


def require_roles(*allowed: Role) -> Callable:
    async def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed and user.role != Role.ADMINISTRATOR:
            raise SpriteError(
                "FORBIDDEN", "role is not allowed for this operation", status_code=403
            )
        return user

    return dependency
