from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.config import get_settings
from most_sprite.db.models import ConfigSnapshot
from most_sprite.domain.enums import ConfigurationStatus, DataMode


@lru_cache
def _read_config(relative_path: str) -> dict[str, Any]:
    path = get_settings().config_root / Path(relative_path)
    if not path.is_file():
        raise RuntimeError(f"required versioned configuration is missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError(f"unsupported configuration schema: {path}")
    return payload


def modulation_configuration() -> dict[str, Any]:
    return deepcopy(_read_config("modulation/most-v1.yaml"))


def qc_configuration() -> dict[str, Any]:
    return deepcopy(_read_config("qc/simulation-v1.yaml"))


_modulation = modulation_configuration()
SIGN_VECTORS: dict[str, list[int]] = {
    key: [int(value) for value in values] for key, values in _modulation["sign_vectors"].items()
}
MODULATION_ANGLES: dict[DataMode, list[tuple[float, float]]] = {
    DataMode(key): [(float(pair[0]), float(pair[1])) for pair in values]
    for key, values in _modulation["angles_deg"].items()
}


def default_instrument_configuration() -> dict[str, Any]:
    settings = get_settings()
    payload = deepcopy(_read_config("instrument/simulation-v1.yaml"))
    payload["detector"]["physical_shape"] = [
        settings.physical_rows,
        settings.physical_columns,
    ]
    payload["detector"]["simulation_shape"] = [
        settings.simulation_rows,
        settings.simulation_columns,
    ]
    payload["modulation"] = modulation_configuration()
    payload["qc"] = qc_configuration()
    return payload


def content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


async def ensure_default_config(session: AsyncSession) -> ConfigSnapshot:
    payload = default_instrument_configuration()
    digest = content_hash(payload)
    existing = await session.scalar(
        select(ConfigSnapshot).where(ConfigSnapshot.content_hash == digest)
    )
    if existing is not None:
        return existing
    snapshot = ConfigSnapshot(
        version=str(payload["version"]),
        status=ConfigurationStatus.UNVERIFIED,
        content_hash=digest,
        payload_json=payload,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def active_config(session: AsyncSession) -> ConfigSnapshot:
    snapshot = await session.scalar(
        select(ConfigSnapshot).order_by(ConfigSnapshot.created_at.desc()).limit(1)
    )
    return snapshot or await ensure_default_config(session)
