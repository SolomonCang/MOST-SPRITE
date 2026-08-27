from __future__ import annotations

import json

import grpc

from most_sprite.config import get_settings
from most_sprite.devices.contracts import DeviceCommand
from most_sprite.devices.simulator import DeviceSimulator


async def serve_device_agent() -> None:
    from most_sprite.schemas.generated import device_agent_pb2, device_agent_pb2_grpc

    simulator = DeviceSimulator()

    class Servicer(device_agent_pb2_grpc.DeviceAgentServicer):
        async def Execute(self, request, context):  # noqa: N802, ANN001
            feedback = await simulator.execute(
                DeviceCommand(
                    command_id=request.command_id,
                    idempotency_key=request.idempotency_key,
                    sequence_id=request.sequence_id,
                    device_id=request.device_id,
                    command_type=request.command_type,
                    parameters=json.loads(request.parameters_json or "{}"),
                    issued_at=request.issued_at,
                    deadline=request.deadline,
                    expected_pre_state=request.expected_pre_state,
                    config_snapshot_id=request.config_snapshot_id,
                    fencing_token=request.fencing_token,
                )
            )
            return device_agent_pb2.DeviceFeedback(
                command_id=feedback.command_id,
                status=feedback.status.value,
                completed_at=feedback.completed_at.isoformat(),
                result_json=json.dumps(feedback.result),
                error_code=feedback.error_code or "",
                error_message=feedback.error_message or "",
            )

        async def GetState(self, request, context):  # noqa: N802, ANN001
            state = await simulator.state(request.device_id)
            return device_agent_pb2.DeviceState(
                device_id=state.device_id,
                state_json=json.dumps(state.values),
                observed_at=state.observed_at.isoformat(),
                fencing_token=state.fencing_token,
            )

        async def InjectFault(self, request, context):  # noqa: N802, ANN001
            feedback = await simulator.inject_fault(request.fault_type, request.active)
            return device_agent_pb2.DeviceFeedback(
                command_id=feedback.command_id,
                status=feedback.status.value,
                completed_at=feedback.completed_at.isoformat(),
                result_json=json.dumps(feedback.result),
            )

    settings = get_settings()
    server = grpc.aio.server()
    device_agent_pb2_grpc.add_DeviceAgentServicer_to_server(Servicer(), server)
    server.add_insecure_port(f"{settings.grpc_host}:{settings.grpc_port}")
    await server.start()
    await server.wait_for_termination()
