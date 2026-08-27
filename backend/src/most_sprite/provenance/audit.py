from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.db.models import AuditEvent
from most_sprite.domain.schemas import CurrentUser


async def record_audit(
    session: AsyncSession,
    user: CurrentUser,
    *,
    action: str,
    resource_type: str,
    correlation_id: str,
    resource_id: str | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor=user.subject,
        role=str(user.role),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        before_json=before or {},
        after_json=after or {},
        correlation_id=correlation_id,
    )
    session.add(event)
    await session.flush()
    return event
