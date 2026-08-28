from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.auth.accounts import list_active_accounts
from most_sprite.auth.dependencies import LOCAL_SESSION_COOKIE, issue_local_session
from most_sprite.config import get_settings
from most_sprite.db.models import UserAccount
from most_sprite.db.session import get_session
from most_sprite.domain.enums import Role
from most_sprite.domain.schemas import (
    AuthConfiguration,
    CurrentUser,
    LocalLoginRequest,
    UserAccountRead,
)
from most_sprite.errors import SpriteError
from most_sprite.provenance import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/configuration", response_model=AuthConfiguration)
async def auth_configuration(session: SessionDep) -> AuthConfiguration:
    settings = get_settings()
    if settings.auth_mode != "dev":
        return AuthConfiguration(auth_mode="oidc")
    accounts = await list_active_accounts(session)
    default_account = next(
        (item for item in accounts if item.username == settings.local_auth_default_username),
        None,
    )
    return AuthConfiguration(
        auth_mode="dev",
        accounts=[UserAccountRead.model_validate(item) for item in accounts],
        default_account_id=UUID(default_account.id) if default_account else None,
    )


@router.post("/login", response_model=CurrentUser)
async def local_login(
    payload: LocalLoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode != "dev" or settings.app_env == "production":
        raise SpriteError(
            "AUTH_FLOW_UNAVAILABLE", "local account selection is unavailable", status_code=404
        )
    account = await session.scalar(
        select(UserAccount).where(
            UserAccount.id == str(payload.account_id),
            UserAccount.is_active.is_(True),
        )
    )
    if account is None:
        raise SpriteError("AUTH_ACCOUNT_NOT_FOUND", "account is not available", status_code=404)
    try:
        role = Role(account.role)
    except ValueError as exc:
        raise SpriteError("INVALID_ROLE", "account has an unknown role", status_code=403) from exc
    user = CurrentUser(
        subject=account.username,
        display_name=account.display_name,
        role=role,
        auth_mode="dev",
    )
    response.set_cookie(
        key=LOCAL_SESSION_COOKIE,
        value=issue_local_session(account),
        max_age=settings.local_auth_session_hours * 3600,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    await record_audit(
        session,
        user,
        action="auth.login",
        resource_type="UserAccount",
        resource_id=account.id,
        correlation_id=request.state.correlation_id,
    )
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(
        key=LOCAL_SESSION_COOKIE,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
