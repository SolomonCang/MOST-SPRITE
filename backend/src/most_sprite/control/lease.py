from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.db.models import ControlLease


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def acquire_or_renew_lease(
    session: AsyncSession, owner_id: str, *, ttl_seconds: float = 15.0
) -> int | None:
    now = datetime.now(UTC)
    lease = await session.scalar(
        select(ControlLease).where(ControlLease.name == "primary").with_for_update()
    )
    if lease is None:
        lease = ControlLease(
            name="primary",
            owner_id=owner_id,
            fencing_token=1,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        session.add(lease)
        await session.flush()
        return lease.fencing_token
    if lease.owner_id != owner_id and _aware(lease.expires_at) > now:
        return None
    if lease.owner_id != owner_id:
        lease.fencing_token += 1
    lease.owner_id = owner_id
    lease.expires_at = now + timedelta(seconds=ttl_seconds)
    await session.flush()
    return lease.fencing_token
