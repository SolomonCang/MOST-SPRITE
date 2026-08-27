"""Persistent idempotency for API mutations that return domain resources."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.db.models import ApiIdempotencyRecord
from most_sprite.errors import SpriteError


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return _digest(encoded)


async def find_idempotent_resource(
    session: AsyncSession,
    *,
    scope: str,
    principal: str,
    key: str,
    payload: Any,
) -> ApiIdempotencyRecord | None:
    principal_hash = _digest(principal)
    key_hash = _digest(key)
    record = await session.scalar(
        select(ApiIdempotencyRecord).where(
            ApiIdempotencyRecord.scope == scope,
            ApiIdempotencyRecord.principal_hash == principal_hash,
            ApiIdempotencyRecord.key_hash == key_hash,
        )
    )
    if record is not None and record.request_hash != _request_digest(payload):
        raise SpriteError(
            "IDEMPOTENCY_CONFLICT",
            "this Idempotency-Key was already used for a different request",
            status_code=409,
            details={"scope": scope},
        )
    return record


async def bind_idempotent_resource(
    session: AsyncSession,
    *,
    scope: str,
    principal: str,
    key: str,
    payload: Any,
    resource_type: str,
    resource_id: str,
) -> ApiIdempotencyRecord:
    record = ApiIdempotencyRecord(
        scope=scope,
        principal_hash=_digest(principal),
        key_hash=_digest(key),
        request_hash=_request_digest(payload),
        resource_type=resource_type,
        resource_id=resource_id,
    )
    session.add(record)
    await session.flush()
    return record
