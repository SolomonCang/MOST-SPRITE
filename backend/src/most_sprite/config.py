from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPRITE_", env_file=".env", extra="ignore", case_sensitive=False
    )

    app_env: Literal["simulation", "test", "production"] = "simulation"
    auth_mode: Literal["dev", "oidc"] = "dev"
    database_url: str = "sqlite+aiosqlite:///./.runtime/sprite.db"
    redis_url: str = "redis://localhost:6379/0"
    config_root: Path = Path("configs")
    data_root: Path = Path(".runtime/data")
    embedded_workers: bool = True
    auto_create_schema: bool = True
    device_agent_target: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50051
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    local_auth_secret: SecretStr | None = Field(default=None, min_length=32)
    local_auth_default_username: str = "administrator"
    local_auth_session_hours: int = Field(default=12, ge=1, le=168)
    allow_legacy_dev_headers: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )
    software_version: str = "0.1.0"
    software_commit: str = "WORKTREE"
    simulation_exposure_scale: float = 0.01
    simulation_rows: int = 256
    simulation_columns: int = 256
    physical_rows: int = 4096
    physical_columns: int = 4096
    processing_claim_timeout_seconds: float = 300.0
    # JSON object supplied through SPRITE_IMPORT_ROOTS, for example
    # {"cadc": "/srv/cadc", "night": "/data/espadons/2026-08-27"}.
    # Clients only ever see the stable key; absolute server paths remain an
    # operator-controlled trust boundary.
    import_roots: dict[str, Path] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_security_boundary(self) -> Settings:
        normalized_roots: dict[str, Path] = {}
        for name, root in self.import_roots.items():
            clean_name = name.strip()
            if not clean_name or "/" in clean_name or "\\" in clean_name:
                raise ValueError("SPRITE_IMPORT_ROOTS keys must be simple non-empty names")
            normalized_roots[clean_name] = root.expanduser().resolve()
        self.import_roots = normalized_roots
        if self.app_env == "production":
            if self.auth_mode != "oidc":
                raise ValueError("production requires SPRITE_AUTH_MODE=oidc")
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("production requires OIDC issuer and audience")
            if self.auto_create_schema:
                raise ValueError("production must run Alembic instead of auto-creating schema")
        elif self.auth_mode == "dev" and self.local_auth_secret is None:
            raise ValueError(
                "development auth requires SPRITE_LOCAL_AUTH_SECRET with at least 32 characters"
            )
        return self

    def prepare_runtime(self) -> None:
        for path in (
            self.data_root,
            self.data_root / "raw",
            self.data_root / "incoming",
            self.data_root / "products",
            self.data_root / "quicklook",
        ):
            path.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            Path(".runtime").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_runtime()
    return settings
