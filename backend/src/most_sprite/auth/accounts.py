from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.db.models import UserAccount
from most_sprite.domain.enums import Role


@dataclass(frozen=True)
class PreconfiguredAccount:
    id: str
    username: str
    display_name: str
    role: Role


PRECONFIGURED_ACCOUNTS = (
    PreconfiguredAccount(
        "00000000-0000-4000-8000-000000000001",
        "administrator",
        "Local Administrator",
        Role.ADMINISTRATOR,
    ),
    PreconfiguredAccount(
        "00000000-0000-4000-8000-000000000002",
        "observer",
        "Local Observer",
        Role.OBSERVER,
    ),
    PreconfiguredAccount(
        "00000000-0000-4000-8000-000000000003",
        "instrument-engineer",
        "Local Instrument Engineer",
        Role.INSTRUMENT_ENGINEER,
    ),
    PreconfiguredAccount(
        "00000000-0000-4000-8000-000000000004",
        "data-reducer",
        "Local Data Reducer",
        Role.DATA_REDUCER,
    ),
)


async def ensure_preconfigured_accounts(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(UserAccount.username))).all())
    for account in PRECONFIGURED_ACCOUNTS:
        if account.username not in existing:
            session.add(
                UserAccount(
                    id=account.id,
                    username=account.username,
                    display_name=account.display_name,
                    role=account.role,
                    is_active=True,
                    is_preconfigured=True,
                )
            )


async def list_active_accounts(session: AsyncSession) -> list[UserAccount]:
    return list(
        (
            await session.scalars(
                select(UserAccount)
                .where(UserAccount.is_active.is_(True))
                .order_by(
                    UserAccount.is_preconfigured.desc(),
                    UserAccount.id,
                    UserAccount.username,
                )
            )
        ).all()
    )
