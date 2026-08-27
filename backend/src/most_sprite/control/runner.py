from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import structlog
from sqlalchemy import select, update

from most_sprite.acquisition import AcquisitionService
from most_sprite.config import get_settings
from most_sprite.configuration import MODULATION_ANGLES, qc_configuration
from most_sprite.control.lease import acquire_or_renew_lease
from most_sprite.control.state_machine import assert_transition
from most_sprite.db.models import (
    Alarm,
    Command,
    Exposure,
    InstrumentStateRecord,
    ModulationGroup,
    Sequence,
    utcnow,
)
from most_sprite.db.session import session_scope
from most_sprite.devices import DeviceClient, DeviceCommand, GrpcDeviceClient, InProcessDeviceClient
from most_sprite.domain.enums import (
    AlarmSeverity,
    CommandStatus,
    DataMode,
    EventType,
    ExposureStatus,
    InstrumentState,
    SequenceStatus,
)
from most_sprite.errors import SpriteError
from most_sprite.events import emit_event

logger = structlog.get_logger(__name__)


class ControlRunner:
    def __init__(
        self, device_client: DeviceClient | None = None, owner_id: str | None = None
    ) -> None:
        settings = get_settings()
        if device_client is not None:
            self.device = device_client
        elif settings.device_agent_target:
            self.device = GrpcDeviceClient(settings.device_agent_target)
        else:
            self.device = InProcessDeviceClient()
        self.owner_id = owner_id or f"{socket.gethostname()}-{os.getpid()}"
        self.acquisition = AcquisitionService()
        self._stopping = False
        self._last_idle_refresh = 0.0

    async def run_forever(self, poll_seconds: float = 0.25) -> None:
        while not self._stopping:
            try:
                handled = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("control_poll_retry", error=str(exc))
                handled = False
            if not handled and not self._stopping:
                await asyncio.sleep(poll_seconds)

    def stop(self) -> None:
        self._stopping = True

    async def run_once(self) -> bool:
        async with session_scope() as session:
            token = await acquire_or_renew_lease(session, self.owner_id)
            if token is None:
                return False
            sequence = await session.scalar(
                select(Sequence)
                .where(Sequence.status == SequenceStatus.QUEUED)
                .order_by(Sequence.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if sequence is None:
                await self._refresh_idle_snapshot(session, token)
                return False
            sequence.status = SequenceStatus.RUNNING
            sequence.updated_at = utcnow()
            sequence_id = sequence.id
            await self._complete_action_command(session, sequence.id, {"START", "RESUME"})
            await emit_event(
                session,
                EventType.SEQUENCE_STATE_CHANGED,
                correlation_id=sequence.id,
                sequence_id=sequence.id,
                config_snapshot_id=sequence.config_snapshot_id,
                payload={"status": SequenceStatus.RUNNING},
            )
        try:
            await self._run_sequence(sequence_id, token)
        except Exception as exc:  # the control boundary must always fail safe
            await self._fail_sequence(sequence_id, token, exc)
        return True

    async def _refresh_idle_snapshot(self, session, fencing_token: int) -> None:  # noqa: ANN001
        now = time.monotonic()
        if now - self._last_idle_refresh < 1.0:
            return
        record = await session.get(InstrumentStateRecord, 1)
        assert record is not None
        state = await self.device.state()
        changed = record.devices_json != state.values
        record.observed_at = state.observed_at
        record.fencing_token = fencing_token
        record.devices_json = state.values
        self._last_idle_refresh = now
        if changed:
            await emit_event(
                session,
                EventType.DEVICE_STATE_CHANGED,
                correlation_id=str(uuid4()),
                payload={"state": record.state, "devices": state.values, "heartbeat": True},
            )

    async def _run_sequence(self, sequence_id: str, fencing_token: int) -> None:
        async with session_scope() as session:
            sequence = await session.get(Sequence, sequence_id)
            assert sequence is not None
            mode = DataMode(sequence.mode)
            await self._prepare_instrument(session, sequence, fencing_token)

        subexposures = 4 if mode.is_polarimetric else 1
        for group_index in range(1, sequence.repeats + 1):
            group_id: str | None = None
            if mode.is_polarimetric:
                async with session_scope() as session:
                    group = await session.scalar(
                        select(ModulationGroup).where(
                            ModulationGroup.sequence_id == sequence_id,
                            ModulationGroup.group_index == group_index,
                        )
                    )
                    if group is None:
                        group = ModulationGroup(
                            sequence_id=sequence_id,
                            group_index=group_index,
                            stokes=mode.value[-1],
                        )
                        session.add(group)
                        await session.flush()
                    group_id = group.id
            for sub_index in range(1, subexposures + 1):
                ordinal = (group_index - 1) * subexposures + sub_index
                async with session_scope() as session:
                    sequence = await session.get(Sequence, sequence_id)
                    assert sequence is not None
                    existing = await session.scalar(
                        select(Exposure).where(
                            Exposure.sequence_id == sequence_id,
                            Exposure.sub_index == ordinal,
                            Exposure.status == ExposureStatus.COMMITTED,
                        )
                    )
                    if existing is not None:
                        continue
                    if sequence.status == SequenceStatus.ABORTING:
                        await self._mark_aborted(session, sequence, fencing_token)
                        return
                    if sequence.status == SequenceStatus.PAUSING:
                        await self._mark_paused(session, sequence)
                        return
                await self._take_exposure(
                    sequence_id,
                    group_id,
                    mode,
                    ordinal,
                    sub_index,
                    fencing_token,
                )
                async with session_scope() as session:
                    sequence = await session.get(Sequence, sequence_id)
                    assert sequence is not None
                    status = SequenceStatus(sequence.status)
                    if status == SequenceStatus.ABORTING:
                        await self._mark_aborted(session, sequence, fencing_token)
                        return
                    if status == SequenceStatus.PAUSING:
                        await self._mark_paused(session, sequence)
                        return
                    if status in {
                        SequenceStatus.ABORTED,
                        SequenceStatus.PAUSED,
                        SequenceStatus.FAILED,
                    }:
                        return

        async with session_scope() as session:
            sequence = await session.get(Sequence, sequence_id)
            assert sequence is not None
            status = SequenceStatus(sequence.status)
            if status == SequenceStatus.ABORTING:
                await self._mark_aborted(session, sequence, fencing_token)
                return
            if status == SequenceStatus.PAUSING:
                await self._mark_paused(session, sequence)
                return
            if status != SequenceStatus.RUNNING:
                return
            sequence.status = SequenceStatus.SUCCEEDED
            sequence.updated_at = utcnow()
            await self._transition(session, InstrumentState.STANDBY, fencing_token)
            await emit_event(
                session,
                EventType.SEQUENCE_STATE_CHANGED,
                correlation_id=sequence_id,
                sequence_id=sequence_id,
                config_snapshot_id=sequence.config_snapshot_id,
                payload={"status": SequenceStatus.SUCCEEDED},
            )

    async def _prepare_instrument(
        self,
        session,
        sequence: Sequence,
        fencing_token: int,  # noqa: ANN001
    ) -> None:
        record = await session.get(InstrumentStateRecord, 1)
        assert record is not None
        current = InstrumentState(record.state)
        if current == InstrumentState.SAFE_FAULT:
            raise SpriteError("SAFE_FAULT_LATCHED", "instrument requires an authorized recovery")
        state = await self.device.state()
        if not state.values.get("initialized", False) and current != InstrumentState.OFFLINE:
            # The simulator is a separate process and may restart while the authority
            # database remains available. Reconcile only idle states automatically;
            # an in-flight state still fails safe and requires explicit recovery.
            if current == InstrumentState.READY:
                await self._transition(session, InstrumentState.STANDBY, fencing_token)
                current = InstrumentState.STANDBY
            if current == InstrumentState.STANDBY:
                await self._transition(session, InstrumentState.OFFLINE, fencing_token)
                current = InstrumentState.OFFLINE
            else:
                raise SpriteError(
                    "DEVICE_RESTART_DURING_ACTIVE_STATE",
                    "device agent restarted outside an idle instrument state",
                    retryable=True,
                )
        if current == InstrumentState.OFFLINE:
            await self._transition(session, InstrumentState.INITIALIZING, fencing_token)
            await self._execute_command(
                session, sequence, "ics", "INITIALIZE", {}, fencing_token, "initialize"
            )
            await self._transition(session, InstrumentState.STANDBY, fencing_token)
        await self._transition(session, InstrumentState.PREPARING, fencing_token)
        state = await self.device.state()
        age = (datetime.now(UTC) - state.observed_at).total_seconds()
        if age > float(qc_configuration()["stale_state_seconds"]):
            raise SpriteError("DEVICE_STATE_STALE", "device state is too old for sequence start")
        if not state.values.get("interlock_safe", False):
            raise SpriteError("INTERLOCK_UNSAFE", "simulated hardware interlock is not safe")
        await self._execute_command(
            session,
            sequence,
            "ics",
            "SET_OPTICS",
            {"mode": sequence.mode},
            fencing_token,
            f"optics-{sequence.mode}",
        )
        await self._transition(session, InstrumentState.READY, fencing_token)

    async def _take_exposure(
        self,
        sequence_id: str,
        group_id: str | None,
        mode: DataMode,
        ordinal: int,
        group_sub_index: int,
        fencing_token: int,
    ) -> None:
        async with session_scope() as session:
            sequence = await session.get(Sequence, sequence_id)
            assert sequence is not None
            if sequence.status == SequenceStatus.ABORTING:
                await self._mark_aborted(session, sequence, fencing_token)
                return
            if sequence.status == SequenceStatus.PAUSING:
                await self._mark_paused(session, sequence)
                return
            if mode.is_polarimetric:
                fr1, fr3 = MODULATION_ANGLES[mode][group_sub_index - 1]
            else:
                fr1, fr3 = 0.0, 0.0
            move = await self._execute_command(
                session,
                sequence,
                "polarimeter",
                "MOVE_FR",
                {"fr1_deg": fr1, "fr3_deg": fr3},
                fencing_token,
                f"move-{ordinal}",
            )
            exposure = await session.scalar(
                select(Exposure)
                .where(
                    Exposure.sequence_id == sequence_id,
                    Exposure.sub_index == ordinal,
                    Exposure.status != ExposureStatus.COMMITTED,
                )
                .order_by(Exposure.created_at.desc())
                .limit(1)
            )
            if exposure is None:
                exposure = Exposure(sequence_id=sequence_id, sub_index=ordinal)
                session.add(exposure)
            exposure.group_id = group_id
            exposure.status = ExposureStatus.PENDING
            exposure.fr1_commanded = fr1
            exposure.fr3_commanded = fr3
            exposure.fr1_measured = float(move.result["fr1_measured"])
            exposure.fr3_measured = float(move.result["fr3_measured"])
            tolerance = float(qc_configuration()["angle_tolerance_deg"])
            if (
                abs(exposure.fr1_measured - fr1) > tolerance
                or abs(exposure.fr3_measured - fr3) > tolerance
            ):
                raise SpriteError(
                    "MODULATOR_POSITION_OUT_OF_TOLERANCE",
                    "measured retarder angle is outside the frozen simulation tolerance",
                )
            await session.flush()
            exposure_id = exposure.id
            await self._transition(session, InstrumentState.EXPOSING, fencing_token)
            exposure.status = ExposureStatus.EXPOSING
            exposure.started_at = utcnow()
            started_at = exposure.started_at

        await self._wait_exposure(sequence_id, float(sequence.exposure_time))
        async with session_scope() as session:
            sequence = await session.get(Sequence, sequence_id)
            loaded_exposure = await session.get(Exposure, exposure_id)
            assert sequence is not None and loaded_exposure is not None and started_at is not None
            exposure = loaded_exposure
            if sequence.status == SequenceStatus.ABORTING:
                await self._execute_command(
                    session, sequence, "detector", "ABORT", {}, fencing_token, f"abort-{ordinal}"
                )
                exposure.status = ExposureStatus.FAILED
                await self._mark_aborted(session, sequence, fencing_token)
                return
            settings = get_settings()
            incoming_path = settings.data_root / "incoming" / f"{exposure.id}.npy"
            feedback = await self._execute_command(
                session,
                sequence,
                "detector",
                "EXPOSE",
                {
                    "mode": mode.value,
                    "sub_index": group_sub_index,
                    "rows": settings.simulation_rows,
                    "columns": settings.simulation_columns,
                    "output_path": str(incoming_path.resolve()),
                },
                fencing_token,
                f"expose-{ordinal}",
            )
            exposure.command_id = feedback.command_id
            exposure.fr1_measured = float(feedback.result["fr1_measured"])
            exposure.fr3_measured = float(feedback.result["fr3_measured"])
            exposure.status = ExposureStatus.READING
            await self._transition(session, InstrumentState.READING, fencing_token)
            image = np.load(Path(feedback.result["frame_path"]), allow_pickle=False)
            ended_at = utcnow()
            telemetry = {
                **feedback.result,
                "target": sequence.target_name,
                "mode": mode.value,
                "sub_index": group_sub_index,
                "state_fresh": True,
            }
            device_state = await self.device.state()
            if not device_state.values.get("guider_locked", False):
                raise SpriteError(
                    "GUIDER_LOCK_LOST",
                    "guide lock was lost before the L0 commit boundary",
                    retryable=True,
                )
            telemetry["storage_fault"] = bool(
                device_state.values.get("faults", {}).get("DISK_FULL", False)
                or device_state.values.get("faults", {}).get("NAS_UNAVAILABLE", False)
            )
            await self.acquisition.commit_l0(
                session,
                exposure=exposure,
                mode=mode,
                config_snapshot_id=sequence.config_snapshot_id,
                image=image,
                telemetry=telemetry,
                exposure_time=sequence.exposure_time,
                started_at=started_at,
                ended_at=ended_at,
            )
            sequence.completed_exposures += 1
            sequence.updated_at = utcnow()
            target = (
                InstrumentState.STANDBY
                if sequence.completed_exposures >= sequence.expected_exposures
                else InstrumentState.READY
            )
            await self._transition(session, target, fencing_token)
        with contextlib.suppress(OSError):
            Path(feedback.result["frame_path"]).unlink()

    async def _wait_exposure(self, sequence_id: str, exposure_time: float) -> None:
        duration = max(0.01, exposure_time * get_settings().simulation_exposure_scale)
        elapsed = 0.0
        while elapsed < duration:
            chunk = min(0.1, duration - elapsed)
            await asyncio.sleep(chunk)
            elapsed += chunk
            async with session_scope() as session:
                sequence = await session.get(Sequence, sequence_id)
                if sequence is not None and sequence.status == SequenceStatus.ABORTING:
                    return

    async def _execute_command(
        self,
        session,
        sequence: Sequence,
        device_id: str,
        command_type: str,
        parameters: dict,
        fencing_token: int,
        suffix: str,
    ):
        command_id = str(uuid4())
        idempotency_key = f"{sequence.id}:{sequence.attempt}:{suffix}"
        record = await session.scalar(
            select(Command).where(Command.idempotency_key == idempotency_key)
        )
        if record is not None and record.status == CommandStatus.SUCCEEDED:
            from most_sprite.devices.contracts import DeviceFeedback

            return DeviceFeedback(
                command_id=record.id,
                status=CommandStatus.SUCCEEDED,
                result=record.parameters_json.get("_result", {}),
            )
        deadline = datetime.now(UTC) + timedelta(seconds=30)
        record = record or Command(
            id=command_id,
            idempotency_key=idempotency_key,
            sequence_id=sequence.id,
            device_id=device_id,
            command_type=command_type,
            parameters_json=parameters,
            deadline=deadline,
            fencing_token=fencing_token,
        )
        session.add(record)
        await session.flush()
        feedback = await self.device.execute(
            DeviceCommand(
                command_id=record.id,
                idempotency_key=idempotency_key,
                sequence_id=sequence.id,
                device_id=device_id,
                command_type=command_type,
                parameters=parameters,
                deadline=deadline,
                config_snapshot_id=sequence.config_snapshot_id,
                fencing_token=fencing_token,
            )
        )
        record.status = feedback.status
        record.completed_at = feedback.completed_at
        record.error_code = feedback.error_code
        record.error_message = feedback.error_message
        record.parameters_json = {**parameters, "_result": feedback.result}
        if feedback.status != CommandStatus.SUCCEEDED:
            raise SpriteError(
                feedback.error_code or "DEVICE_COMMAND_FAILED",
                feedback.error_message or "device command failed",
                retryable=feedback.status in {CommandStatus.TIMED_OUT, CommandStatus.FAILED},
            )
        return feedback

    async def _transition(
        self,
        session,
        target: InstrumentState,
        fencing_token: int,  # noqa: ANN001
    ) -> None:
        record = await session.get(InstrumentStateRecord, 1)
        assert record is not None
        current = InstrumentState(record.state)
        if current == target:
            return
        assert_transition(current, target)
        record.target_state = target
        record.state = target
        record.target_state = None
        record.observed_at = utcnow()
        record.fencing_token = fencing_token
        state = await self.device.state()
        record.devices_json = state.values
        await emit_event(
            session,
            EventType.DEVICE_STATE_CHANGED,
            correlation_id=str(uuid4()),
            payload={"previous": current.value, "state": target.value, "devices": state.values},
        )

    async def _mark_paused(self, session, sequence: Sequence) -> None:  # noqa: ANN001
        record = await session.get(InstrumentStateRecord, 1)
        assert record is not None
        if InstrumentState(record.state) == InstrumentState.READY:
            await self._transition(session, InstrumentState.STANDBY, record.fencing_token)
        sequence.status = SequenceStatus.PAUSED
        await self._complete_action_command(session, sequence.id, {"PAUSE"})
        await emit_event(
            session,
            EventType.SEQUENCE_STATE_CHANGED,
            correlation_id=sequence.id,
            sequence_id=sequence.id,
            payload={"status": SequenceStatus.PAUSED},
        )

    async def _mark_aborted(self, session, sequence: Sequence, fencing_token: int) -> None:  # noqa: ANN001
        record = await session.get(InstrumentStateRecord, 1)
        assert record is not None
        current = InstrumentState(record.state)
        if current != InstrumentState.STANDBY:
            await self._transition(session, InstrumentState.STANDBY, fencing_token)
        sequence.status = SequenceStatus.ABORTED
        await self._complete_action_command(session, sequence.id, {"ABORT"})
        await emit_event(
            session,
            EventType.SEQUENCE_STATE_CHANGED,
            correlation_id=sequence.id,
            sequence_id=sequence.id,
            payload={"status": SequenceStatus.ABORTED},
        )

    async def _fail_sequence(self, sequence_id: str, fencing_token: int, exc: Exception) -> None:
        logger.exception("control_sequence_failed", sequence_id=sequence_id, error=str(exc))
        async with session_scope() as session:
            sequence = await session.get(Sequence, sequence_id)
            if sequence is None:
                return
            sequence.status = SequenceStatus.FAILED
            sequence.last_error_code = getattr(exc, "code", "CONTROL_FAILURE")
            sequence.last_error_message = str(exc)
            await session.execute(
                update(Exposure)
                .where(
                    Exposure.sequence_id == sequence_id,
                    Exposure.status.in_(
                        [
                            ExposureStatus.PENDING,
                            ExposureStatus.EXPOSING,
                            ExposureStatus.READING,
                        ]
                    ),
                )
                .values(status=ExposureStatus.FAILED)
            )
            state = await session.get(InstrumentStateRecord, 1)
            assert state is not None
            current = InstrumentState(state.state)
            if current != InstrumentState.SAFE_FAULT:
                if (
                    InstrumentState.SAFE_FAULT
                    in __import__(
                        "most_sprite.control.state_machine", fromlist=["ALLOWED_TRANSITIONS"]
                    ).ALLOWED_TRANSITIONS[current]
                ):
                    await self._transition(session, InstrumentState.SAFE_FAULT, fencing_token)
                else:
                    state.state = InstrumentState.SAFE_FAULT
                    state.observed_at = utcnow()
            session.add(
                Alarm(
                    sequence_id=sequence_id,
                    severity=AlarmSeverity.SERIOUS,
                    reason_code=sequence.last_error_code,
                    message=str(exc),
                    protective_action="close shutter and stop simulated motion",
                    recovery_condition="clear fault and request authorized recovery",
                )
            )
            await emit_event(
                session,
                EventType.ALARM_RAISED,
                correlation_id=sequence_id,
                sequence_id=sequence_id,
                payload={"reason_code": sequence.last_error_code, "message": str(exc)},
            )
            with contextlib.suppress(Exception):
                await self._execute_command(
                    session, sequence, "ics", "SAFE", {}, fencing_token, "safe-fault"
                )

    async def _complete_action_command(
        self, session, sequence_id: str, command_types: set[str]  # noqa: ANN001
    ) -> None:
        command = await session.scalar(
            select(Command)
            .where(
                Command.sequence_id == sequence_id,
                Command.command_type.in_(command_types),
                Command.status == CommandStatus.ACCEPTED,
            )
            .order_by(Command.issued_at.desc())
            .limit(1)
        )
        if command is not None:
            command.status = CommandStatus.SUCCEEDED
            command.completed_at = utcnow()


async def recover_instrument() -> None:
    async with session_scope() as session:
        record = await session.get(InstrumentStateRecord, 1)
        assert record is not None
        if InstrumentState(record.state) != InstrumentState.SAFE_FAULT:
            raise SpriteError("RECOVERY_NOT_REQUIRED", "instrument is not in SAFE_FAULT")
        assert_transition(InstrumentState.SAFE_FAULT, InstrumentState.OFFLINE)
        record.state = InstrumentState.OFFLINE
        record.observed_at = utcnow()
