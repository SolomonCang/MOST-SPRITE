from __future__ import annotations

import asyncio

import pytest
from most_sprite.control.runner import ControlRunner
from most_sprite.devices import InProcessDeviceClient


@pytest.mark.asyncio
async def test_control_loop_retries_a_transient_device_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ControlRunner(device_client=InProcessDeviceClient())
    attempts = 0

    async def flaky_poll() -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("simulated gRPC restart")
        runner.stop()
        return False

    monkeypatch.setattr(runner, "run_once", flaky_poll)

    await asyncio.wait_for(runner.run_forever(poll_seconds=0), timeout=1.0)

    assert attempts == 2
