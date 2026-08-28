from __future__ import annotations

import pytest
from most_sprite.config import Settings
from most_sprite.configuration import content_hash, default_instrument_configuration
from pydantic import ValidationError


def test_production_fails_closed_without_oidc() -> None:
    with pytest.raises(ValidationError, match="production requires SPRITE_AUTH_MODE=oidc"):
        Settings(app_env="production", auth_mode="dev", auto_create_schema=False)
    with pytest.raises(ValidationError, match="production requires OIDC issuer and audience"):
        Settings(app_env="production", auth_mode="oidc", auto_create_schema=False)


def test_production_accepts_only_explicit_oidc_and_alembic_boundary() -> None:
    settings = Settings(
        app_env="production",
        auth_mode="oidc",
        oidc_issuer="https://identity.example.invalid",
        oidc_audience="most-sprite",
        auto_create_schema=False,
    )
    assert settings.auth_mode == "oidc"
    with pytest.raises(ValidationError, match="production must run Alembic"):
        Settings(
            app_env="production",
            auth_mode="oidc",
            oidc_issuer="https://identity.example.invalid",
            oidc_audience="most-sprite",
            auto_create_schema=True,
        )


def test_local_auth_requires_a_machine_key() -> None:
    with pytest.raises(ValidationError, match="SPRITE_LOCAL_AUTH_SECRET"):
        Settings(app_env="simulation", auth_mode="dev", local_auth_secret=None)


def test_simulation_configuration_is_versioned_unverified_and_deterministic() -> None:
    configuration = default_instrument_configuration()
    assert configuration["version"] == "simulation-v1"
    assert configuration["status"] == "UNVERIFIED"
    assert configuration["publication_allowed"] is False
    assert configuration["detector"]["physical_shape"] == [4096, 4096]
    assert configuration["wavelength"]["type"] == "UNVERIFIED"
    assert content_hash(configuration) == content_hash(default_instrument_configuration())
