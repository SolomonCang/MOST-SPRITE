from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from most_sprite.devices.contracts import DeviceCommand
from most_sprite.devices.simulator import DeviceSimulator
from most_sprite.domain.enums import CommandStatus


def command(*, command_id: str, key: str, token: int, command_type: str = "INITIALIZE"):
    return DeviceCommand(
        command_id=command_id,
        idempotency_key=key,
        sequence_id="11111111-1111-1111-1111-111111111111",
        device_id="ics",
        command_type=command_type,
        parameters={},
        deadline=datetime.now(UTC) + timedelta(seconds=10),
        config_snapshot_id="22222222-2222-2222-2222-222222222222",
        fencing_token=token,
    )


@pytest.mark.asyncio
async def test_repeated_idempotency_key_returns_original_feedback() -> None:
    simulator = DeviceSimulator()
    first = await simulator.execute(command(command_id="one", key="same-key", token=1))
    second = await simulator.execute(command(command_id="two", key="same-key", token=1))
    assert first.status == CommandStatus.SUCCEEDED
    assert second == first
    assert second.command_id == "one"


@pytest.mark.asyncio
async def test_stale_fencing_token_is_rejected() -> None:
    simulator = DeviceSimulator()
    await simulator.execute(command(command_id="new", key="new-leader", token=5))
    stale = await simulator.execute(command(command_id="old", key="old-leader", token=4))
    assert stale.status == CommandStatus.REJECTED
    assert stale.error_code == "STALE_FENCING_TOKEN"
