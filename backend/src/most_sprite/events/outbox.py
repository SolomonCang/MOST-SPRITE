from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.db.models import OutboxEvent
from most_sprite.domain.enums import EventType


async def emit_event(
    session: AsyncSession,
    event_type: EventType | str,
    *,
    correlation_id: str,
    payload: dict[str, Any],
    causation_id: str | None = None,
    sequence_id: str | None = None,
    group_id: str | None = None,
    exposure_id: str | None = None,
    config_snapshot_id: str | None = None,
) -> OutboxEvent:
    event = OutboxEvent(
        event_type=str(event_type),
        correlation_id=correlation_id,
        causation_id=causation_id,
        sequence_id=sequence_id,
        group_id=group_id,
        exposure_id=exposure_id,
        config_snapshot_id=config_snapshot_id,
        payload_json=payload,
    )
    session.add(event)
    await session.flush()
    return event
