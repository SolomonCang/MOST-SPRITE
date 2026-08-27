from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from most_sprite.domain.enums import CommandStatus


class DeviceCommand(BaseModel):
    command_id: str
    idempotency_key: str
    sequence_id: str
    device_id: str
    command_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deadline: datetime
    expected_pre_state: str = "ANY"
    config_snapshot_id: str
    fencing_token: int


class DeviceFeedback(BaseModel):
    command_id: str
    status: CommandStatus
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class DeviceState(BaseModel):
    device_id: str
    values: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fencing_token: int = 0
