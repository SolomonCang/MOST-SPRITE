from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime

import grpc

from most_sprite.devices.contracts import DeviceCommand, DeviceFeedback, DeviceState
from most_sprite.devices.simulator import DeviceSimulator
from most_sprite.domain.enums import CommandStatus


class DeviceClient(ABC):
    @abstractmethod
    async def execute(self, command: DeviceCommand) -> DeviceFeedback: ...

    @abstractmethod
    async def state(self, device_id: str = "all") -> DeviceState: ...

    @abstractmethod
    async def inject_fault(self, fault_type: str, active: bool) -> DeviceFeedback: ...


class InProcessDeviceClient(DeviceClient):
    def __init__(self, simulator: DeviceSimulator | None = None) -> None:
        self.simulator = simulator or DeviceSimulator()

    async def execute(self, command: DeviceCommand) -> DeviceFeedback:
        return await self.simulator.execute(command)

    async def state(self, device_id: str = "all") -> DeviceState:
        return await self.simulator.state(device_id)

    async def inject_fault(self, fault_type: str, active: bool) -> DeviceFeedback:
        return await self.simulator.inject_fault(fault_type, active)


class GrpcDeviceClient(DeviceClient):
    def __init__(self, target: str) -> None:
        from most_sprite.schemas.generated import device_agent_pb2_grpc

        self.channel = grpc.aio.insecure_channel(
            target,
            options=[("grpc.max_send_message_length", 8 * 1024 * 1024)],
        )
        self.stub = device_agent_pb2_grpc.DeviceAgentStub(self.channel)

    async def execute(self, command: DeviceCommand) -> DeviceFeedback:
        from most_sprite.schemas.generated import device_agent_pb2

        response = await self.stub.Execute(
            device_agent_pb2.DeviceCommand(
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                sequence_id=command.sequence_id,
                device_id=command.device_id,
                command_type=command.command_type,
                parameters_json=json.dumps(command.parameters),
                issued_at=command.issued_at.isoformat(),
                deadline=command.deadline.isoformat(),
                expected_pre_state=command.expected_pre_state,
                config_snapshot_id=command.config_snapshot_id,
                fencing_token=command.fencing_token,
            )
        )
        return DeviceFeedback(
            command_id=response.command_id,
            status=CommandStatus(response.status),
            completed_at=datetime.fromisoformat(response.completed_at),
            result=json.loads(response.result_json or "{}"),
            error_code=response.error_code or None,
            error_message=response.error_message or None,
        )

    async def state(self, device_id: str = "all") -> DeviceState:
        from most_sprite.schemas.generated import device_agent_pb2

        response = await self.stub.GetState(device_agent_pb2.StateRequest(device_id=device_id))
        return DeviceState(
            device_id=response.device_id,
            values=json.loads(response.state_json or "{}"),
            observed_at=datetime.fromisoformat(response.observed_at),
            fencing_token=response.fencing_token,
        )

    async def inject_fault(self, fault_type: str, active: bool) -> DeviceFeedback:
        from most_sprite.schemas.generated import device_agent_pb2

        response = await self.stub.InjectFault(
            device_agent_pb2.FaultRequest(
                fault_type=fault_type, active=active, parameters_json="{}"
            )
        )
        return DeviceFeedback(
            command_id=response.command_id,
            status=CommandStatus(response.status),
            completed_at=datetime.fromisoformat(response.completed_at),
            result=json.loads(response.result_json or "{}"),
            error_code=response.error_code or None,
            error_message=response.error_message or None,
        )
