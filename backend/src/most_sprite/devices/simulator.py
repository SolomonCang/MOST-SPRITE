from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from most_sprite.configuration import SIGN_VECTORS, default_instrument_configuration
from most_sprite.devices.contracts import DeviceCommand, DeviceFeedback, DeviceState
from most_sprite.domain.enums import CommandStatus, DataMode
from most_sprite.pipeline.simulation import base_spectrum, channel_centers, channel_roles


class DeviceSimulator:
    """Deterministic, fenced simulator for all vertical-slice device roles."""

    def __init__(self) -> None:
        self._feedback: dict[str, DeviceFeedback] = {}
        self._last_fencing_token = 0
        self._faults: dict[str, bool] = {}
        self._values: dict[str, Any] = {
            "connected": True,
            "initialized": False,
            "fr1_deg": 0.0,
            "fr3_deg": 0.0,
            "optical_mode": "STANDBY",
            "guider_locked": True,
            "temperature_c": 18.0,
            "humidity_percent": 25.0,
            "interlock_safe": True,
        }

    async def execute(self, command: DeviceCommand) -> DeviceFeedback:
        cached = self._feedback.get(command.idempotency_key)
        if cached is not None:
            return cached
        if command.fencing_token < self._last_fencing_token:
            return self._remember(
                command,
                DeviceFeedback(
                    command_id=command.command_id,
                    status=CommandStatus.REJECTED,
                    error_code="STALE_FENCING_TOKEN",
                    error_message="command was issued by a stale control leader",
                ),
            )
        self._last_fencing_token = command.fencing_token
        if datetime.now(UTC) > command.deadline:
            return self._remember(
                command,
                DeviceFeedback(
                    command_id=command.command_id,
                    status=CommandStatus.TIMED_OUT,
                    error_code="DEADLINE_EXCEEDED",
                    error_message="command deadline elapsed before execution",
                ),
            )
        if self._faults.get("COMMUNICATION"):
            return self._remember(
                command,
                DeviceFeedback(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    error_code="COMMUNICATION_LOST",
                    error_message="simulated device network is unavailable",
                ),
            )
        if self._faults.get("LIMIT") and command.command_type in {"MOVE_FR", "SET_OPTICS"}:
            return self._remember(
                command,
                DeviceFeedback(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    error_code="HARD_LIMIT_ACTIVE",
                    error_message="simulated hard limit blocked movement",
                ),
            )
        if self._faults.get("POSITION_TIMEOUT") and command.command_type == "MOVE_FR":
            await asyncio.sleep(0)
            return self._remember(
                command,
                DeviceFeedback(
                    command_id=command.command_id,
                    status=CommandStatus.TIMED_OUT,
                    error_code="POSITION_NOT_REACHED",
                    error_message="simulated mechanism did not settle",
                ),
            )

        handler = getattr(self, f"_handle_{command.command_type.lower()}", None)
        if handler is None:
            feedback = DeviceFeedback(
                command_id=command.command_id,
                status=CommandStatus.REJECTED,
                error_code="UNKNOWN_COMMAND",
                error_message=f"unsupported command {command.command_type}",
            )
        else:
            feedback = await handler(command)
        return self._remember(command, feedback)

    def _remember(self, command: DeviceCommand, feedback: DeviceFeedback) -> DeviceFeedback:
        self._feedback[command.idempotency_key] = feedback
        return feedback

    async def _handle_initialize(self, command: DeviceCommand) -> DeviceFeedback:
        self._values.update(
            initialized=True,
            interlock_safe=not self._faults.get("INTERLOCK_OPEN", False),
            optical_mode="STANDBY",
        )
        return DeviceFeedback(command_id=command.command_id, status=CommandStatus.SUCCEEDED)

    async def _handle_set_optics(self, command: DeviceCommand) -> DeviceFeedback:
        mode = DataMode(command.parameters["mode"])
        self._values["optical_mode"] = mode.value
        self._values["wollaston"] = "IN" if mode.is_polarimetric else "OUT"
        self._values["wedge"] = "OUT" if mode.is_polarimetric else "IN"
        return DeviceFeedback(
            command_id=command.command_id,
            status=CommandStatus.SUCCEEDED,
            result={"optical_mode": mode.value},
        )

    async def _handle_move_fr(self, command: DeviceCommand) -> DeviceFeedback:
        fr1 = float(command.parameters["fr1_deg"])
        fr3 = float(command.parameters["fr3_deg"])
        seed = int(hashlib.sha256(command.command_id.encode()).hexdigest()[:8], 16)
        jitter = ((seed % 101) - 50) / 10000
        self._values["fr1_deg"] = fr1 + jitter
        self._values["fr3_deg"] = fr3 - jitter
        return DeviceFeedback(
            command_id=command.command_id,
            status=CommandStatus.SUCCEEDED,
            result={"fr1_measured": fr1 + jitter, "fr3_measured": fr3 - jitter},
        )

    async def _handle_expose(self, command: DeviceCommand) -> DeviceFeedback:
        if not self._values["initialized"]:
            return DeviceFeedback(
                command_id=command.command_id,
                status=CommandStatus.REJECTED,
                error_code="NOT_INITIALIZED",
                error_message="simulator must be initialized before exposure",
            )
        if self._faults.get("GUIDER_LOST"):
            self._values["guider_locked"] = False
        if self._faults.get("CCD_READOUT"):
            return DeviceFeedback(
                command_id=command.command_id,
                status=CommandStatus.FAILED,
                error_code="CCD_READOUT_FAILED",
                error_message="simulated detector readout failed",
            )
        output_path = Path(command.parameters["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mode = DataMode(command.parameters["mode"])
        rows = int(command.parameters["rows"])
        columns = int(command.parameters["columns"])
        sub_index = int(command.parameters["sub_index"])
        image = self._make_frame(mode, sub_index, rows, columns, command.command_id)
        np.save(output_path, image, allow_pickle=False)
        return DeviceFeedback(
            command_id=command.command_id,
            status=CommandStatus.SUCCEEDED,
            result={
                "frame_path": str(output_path),
                "shape": [rows, columns],
                "fr1_measured": self._values["fr1_deg"],
                "fr3_measured": self._values["fr3_deg"],
                "guider_locked": self._values["guider_locked"],
                "storage_fault": self._faults.get("DISK_FULL", False)
                or self._faults.get("NAS_UNAVAILABLE", False),
            },
        )

    async def _handle_abort(self, command: DeviceCommand) -> DeviceFeedback:
        self._values["shutter"] = "CLOSED"
        return DeviceFeedback(command_id=command.command_id, status=CommandStatus.SUCCEEDED)

    async def _handle_safe(self, command: DeviceCommand) -> DeviceFeedback:
        self._values.update(shutter="CLOSED", optical_mode="SAFE", interlock_safe=True)
        return DeviceFeedback(command_id=command.command_id, status=CommandStatus.SUCCEEDED)

    def _make_frame(
        self, mode: DataMode, sub_index: int, rows: int, columns: int, command_id: str
    ) -> np.ndarray:
        seed = int(hashlib.sha256(command_id.encode()).hexdigest()[:16], 16)
        rng = np.random.default_rng(seed)
        configuration = default_instrument_configuration()
        signal = configuration["simulation_signal"]
        spectrograph = configuration["spectrograph"]
        detector = configuration["detector"]
        frame = np.full((rows, columns), float(signal["bias_adu"]), dtype=np.float64)
        frame += rng.normal(0.0, float(signal["read_noise_adu"]), frame.shape)
        y = np.arange(rows, dtype=np.float64)[:, None]
        centers = channel_centers(rows, mode)
        roles = channel_roles(mode)
        science_sign = float(SIGN_VECTORS["science"][max(0, min(3, sub_index - 1))])
        injected = float(signal["injected_fraction"].get(mode.value, 0.0))

        for order_index in range(len(next(iter(centers.values())))):
            spectrum = float(spectrograph["simulation_peak_adu"]) * base_spectrum(
                columns, order_index
            )
            for role in roles:
                if mode.is_polarimetric:
                    modulation = science_sign * injected
                    role_scale = (1 + modulation) / 2 if role == "O_BEAM" else (1 - modulation) / 2
                    role_scale *= float(signal["polar_throughput"][role])
                else:
                    role_scale = float(signal["nonpolar_role_scale"][role])
                profile_sigma = float(spectrograph["simulation_profile_sigma_px"])
                profile = np.exp(-0.5 * ((y - centers[role][order_index]) / profile_sigma) ** 2)
                profile /= profile.sum(axis=0, keepdims=True)
                expected = profile * (spectrum * role_scale)[None, :]
                frame += rng.poisson(np.clip(expected, 0, None))
        return np.clip(np.rint(frame), 0, float(detector["saturation_adu"])).astype(np.uint16)

    async def state(self, device_id: str = "all") -> DeviceState:
        observed = datetime.now(UTC)
        if self._faults.get("STALE_STATE"):
            observed = observed.replace(year=observed.year - 1)
        return DeviceState(
            device_id=device_id,
            values={**self._values, "faults": dict(self._faults)},
            observed_at=observed,
            fencing_token=self._last_fencing_token,
        )

    async def inject_fault(self, fault_type: str, active: bool) -> DeviceFeedback:
        normalized = fault_type.upper()
        self._faults[normalized] = active
        if normalized == "GUIDER_LOST" and not active:
            self._values["guider_locked"] = True
        if normalized == "INTERLOCK_OPEN":
            self._values["interlock_safe"] = not active
        return DeviceFeedback(
            command_id=f"fault-{fault_type.lower()}",
            status=CommandStatus.SUCCEEDED,
            result={"fault_type": normalized, "active": active},
        )
