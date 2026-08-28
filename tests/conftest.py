from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SPRITE_LOCAL_AUTH_SECRET", "pytest-local-auth-key-2026-change-me")


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_path = tmp_path / "sprite-test.db"
    data_root = tmp_path / "data"
    monkeypatch.setenv("SPRITE_APP_ENV", "simulation")
    monkeypatch.setenv("SPRITE_AUTH_MODE", "dev")
    monkeypatch.setenv("SPRITE_LOCAL_AUTH_SECRET", "pytest-local-auth-key-2026-change-me")
    monkeypatch.setenv("SPRITE_ALLOW_LEGACY_DEV_HEADERS", "true")
    monkeypatch.setenv("SPRITE_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("SPRITE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("SPRITE_EMBEDDED_WORKERS", "true")
    monkeypatch.setenv("SPRITE_AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("SPRITE_SIMULATION_EXPOSURE_SCALE", "0.001")
    monkeypatch.setenv("SPRITE_SIMULATION_ROWS", "96")
    monkeypatch.setenv("SPRITE_SIMULATION_COLUMNS", "128")

    from most_sprite.config import get_settings
    from most_sprite.db.session import dispose_database

    get_settings.cache_clear()
    asyncio.run(dispose_database())

    from most_sprite.api.app import create_app

    with TestClient(create_app()) as client:
        yield client

    get_settings.cache_clear()
    asyncio.run(dispose_database())


@pytest.fixture
def observer_headers() -> dict[str, str]:
    return {"X-SPRITE-User": "test-observer", "X-SPRITE-Role": "observer"}
