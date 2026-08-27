from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from most_sprite.config import get_settings
from most_sprite.control import ControlRunner
from most_sprite.devices import DeviceClient, GrpcDeviceClient, InProcessDeviceClient
from most_sprite.scheduler import OutboxScheduler


@dataclass(slots=True)
class Runtime:
    device: DeviceClient
    control: ControlRunner | None = None
    scheduler: OutboxScheduler | None = None
    tasks: list[asyncio.Task] = field(default_factory=list)

    @classmethod
    def build(cls) -> Runtime:
        settings = get_settings()
        device: DeviceClient = (
            GrpcDeviceClient(settings.device_agent_target)
            if settings.device_agent_target
            else InProcessDeviceClient()
        )
        if not settings.embedded_workers:
            return cls(device=device)
        control = ControlRunner(device_client=device, owner_id="embedded-api")
        scheduler = OutboxScheduler(inline_processing=True)
        return cls(device=device, control=control, scheduler=scheduler)

    async def start(self) -> None:
        if self.control:
            self.tasks.append(
                asyncio.create_task(self.control.run_forever(), name="sprite-control")
            )
        if self.scheduler:
            self.tasks.append(
                asyncio.create_task(self.scheduler.run_forever(), name="sprite-scheduler")
            )

    async def stop(self) -> None:
        if self.control:
            self.control.stop()
        if self.scheduler:
            self.scheduler.stop()
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
