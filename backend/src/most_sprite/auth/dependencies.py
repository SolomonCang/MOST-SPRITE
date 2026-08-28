from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import jwt
from fastapi import Cookie, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.config import get_settings
from most_sprite.db.models import UserAccount
from most_sprite.db.session import get_session, session_scope
from most_sprite.domain.enums import Role
from most_sprite.domain.schemas import CurrentUser
from most_sprite.errors import SpriteError

bearer = HTTPBearer(auto_error=False)
_jwks_clients: dict[str, PyJWKClient] = {}
LOCAL_SESSION_COOKIE = "sprite_session"
LOCAL_SESSION_ISSUER = "most-sprite"
LOCAL_SESSION_AUDIENCE = "most-sprite-local"


def _dev_identity(x_sprite_user: str | None, x_sprite_role: str | None) -> CurrentUser:
    try:
        role = Role(x_sprite_role or Role.OBSERVER)
    except ValueError as exc:
        raise SpriteError("INVALID_ROLE", "unknown development role", status_code=403) from exc
    subject = (x_sprite_user or "local-observer").strip()
    return CurrentUser(subject=subject, display_name=subject, role=role, auth_mode="dev")


def issue_local_session(account: UserAccount) -> str:
    settings = get_settings()
    if settings.local_auth_secret is None:
        raise SpriteError(
            "AUTH_MISCONFIGURED",
            "local authentication key is not configured",
            status_code=503,
        )
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": LOCAL_SESSION_ISSUER,
            "aud": LOCAL_SESSION_AUDIENCE,
            "sub": account.username,
            "iat": now,
            "exp": now + timedelta(hours=settings.local_auth_session_hours),
            "jti": str(uuid4()),
        },
        settings.local_auth_secret.get_secret_value(),
        algorithm="HS256",
    )


async def _local_session_identity(
    session_token: str, session: AsyncSession
) -> CurrentUser:
    settings = get_settings()
    if settings.local_auth_secret is None:
        raise SpriteError(
            "AUTH_MISCONFIGURED",
            "local authentication key is not configured",
            status_code=503,
        )
    try:
        claims = jwt.decode(
            session_token,
            settings.local_auth_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=LOCAL_SESSION_AUDIENCE,
            issuer=LOCAL_SESSION_ISSUER,
        )
        username = str(claims["sub"])
    except (KeyError, jwt.PyJWTError) as exc:
        raise SpriteError(
            "AUTH_SESSION_INVALID", "local session is invalid or expired", status_code=401
        ) from exc
    account = await session.scalar(
        select(UserAccount).where(
            UserAccount.username == username,
            UserAccount.is_active.is_(True),
        )
    )
    if account is None:
        raise SpriteError("AUTH_ACCOUNT_DISABLED", "account is not available", status_code=401)
    try:
        role = Role(account.role)
    except ValueError as exc:
        raise SpriteError("INVALID_ROLE", "account has an unknown role", status_code=403) from exc
    return CurrentUser(
        subject=account.username,
        display_name=account.display_name,
        role=role,
        auth_mode="dev",
    )


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
    *,
    token: str | None,
    session_token: str | None = None,
    x_sprite_user: str | None = None,
    x_sprite_role: str | None = None,
    session: AsyncSession | None = None,
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode == "dev":
        if settings.app_env == "production":
            raise SpriteError("AUTH_MISCONFIGURED", "development auth is disabled", status_code=503)
        if settings.allow_legacy_dev_headers and (x_sprite_user or x_sprite_role):
            return _dev_identity(x_sprite_user, x_sprite_role)
        if not session_token:
            raise SpriteError("AUTH_REQUIRED", "local session required", status_code=401)
        if session is not None:
            return await _local_session_identity(session_token, session)
        async with session_scope() as scoped_session:
            return await _local_session_identity(session_token, scoped_session)
    if not token:
        raise SpriteError("AUTH_REQUIRED", "bearer token required", status_code=401)
    return await _oidc_identity(token)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session_token: str | None = Cookie(default=None, alias=LOCAL_SESSION_COOKIE),
    x_sprite_user: str | None = Header(default=None),
    x_sprite_role: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    return await authenticate_identity(
        token=credentials.credentials if credentials else None,
        session_token=session_token,
        x_sprite_user=x_sprite_user,
        x_sprite_role=x_sprite_role,
        session=session,
    )


def require_roles(*allowed: Role) -> Callable:
    async def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed and user.role != Role.ADMINISTRATOR:
            raise SpriteError(
                "FORBIDDEN", "role is not allowed for this operation", status_code=403
            )
        return user

    return dependency
