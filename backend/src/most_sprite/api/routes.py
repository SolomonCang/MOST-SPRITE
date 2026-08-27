from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import numpy as np
from astropy.io import fits
from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.api.idempotency import (
    bind_idempotent_resource,
    find_idempotent_resource,
)
from most_sprite.auth import authenticate_identity, current_user, require_roles
from most_sprite.calibration import approve_calibration_set, ensure_calibration_run
from most_sprite.config import get_settings
from most_sprite.configuration import active_config
from most_sprite.control.runner import recover_instrument
from most_sprite.control.validation import validate_sequence_request
from most_sprite.db.models import (
    Alarm,
    Calibration,
    CalibrationRun,
    CalibrationSet,
    Command,
    Exposure,
    ImportBatch,
    ImportInspection,
    InstrumentStateRecord,
    OutboxEvent,
    ProcessingRun,
    Product,
    ProductInput,
    QCResult,
    RawFile,
    Sequence,
    TaskRun,
    utcnow,
)
from most_sprite.db.session import get_session, session_scope
from most_sprite.domain.enums import (
    CommandStatus,
    ConfigurationStatus,
    EventType,
    InstrumentState,
    ProductLevel,
    PublicationStatus,
    QCFlag,
    Role,
    SequenceStatus,
)
from most_sprite.domain.schemas import (
    CalibrationCreate,
    CalibrationRead,
    CalibrationRunRead,
    CalibrationRunRequest,
    CalibrationSetApproval,
    CalibrationSetRead,
    CommandAccepted,
    CommandRead,
    CurrentUser,
    ExposureRead,
    ImportBatchRead,
    ImportCommitRequest,
    ImportInspectionRead,
    ImportInspectionRequest,
    InstrumentSnapshot,
    ProcessingRunRead,
    ProcessingRunRequest,
    ProductPublicationRequest,
    ProductRead,
    SequenceRead,
    SequenceRequest,
    SequenceValidation,
)
from most_sprite.errors import SpriteError
from most_sprite.events import emit_event
from most_sprite.imports import commit_import, inspect_import_directory
from most_sprite.products.processing import ensure_processing_run
from most_sprite.provenance import record_audit

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


def _correlation(request: Request) -> str:
    return request.state.correlation_id


@router.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sprite-api"}


@router.get("/api/v1/me")
async def me(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    return user


@router.get("/api/v1/commands/{command_id}", response_model=CommandRead)
async def get_command(
    command_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> Command:
    command = await session.get(Command, str(command_id))
    if command is None:
        raise SpriteError("COMMAND_NOT_FOUND", "command does not exist", status_code=404)
    return command


@router.post("/api/v1/sequences:validate", response_model=SequenceValidation)
async def validate_sequence(payload: SequenceRequest, session: SessionDep) -> SequenceValidation:
    snapshot = await active_config(session)
    return validate_sequence_request(payload, snapshot)


@router.post("/api/v1/sequences", status_code=202, response_model=CommandAccepted)
async def create_sequence(
    payload: SequenceRequest,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.OBSERVER, Role.INSTRUMENT_ENGINEER)),
) -> CommandAccepted:
    existing = await session.scalar(
        select(Sequence).where(Sequence.idempotency_key == idempotency_key)
    )
    if existing is not None:
        command = await session.scalar(
            select(Command).where(Command.idempotency_key == f"api-create:{idempotency_key}")
        )
        assert command is not None
        return CommandAccepted(
            command_id=UUID(command.id),
            resource_id=UUID(existing.id),
            status=CommandStatus(command.status),
        )
    snapshot = await active_config(session)
    validation = validate_sequence_request(payload, snapshot)
    if not validation.valid:
        raise SpriteError(
            "SEQUENCE_VALIDATION_FAILED",
            "sequence has blocking validation issues",
            status_code=422,
            details={"issues": [issue.model_dump() for issue in validation.issues]},
        )
    command = Command(
        idempotency_key=f"api-create:{idempotency_key}",
        device_id="api",
        command_type="CREATE_SEQUENCE",
        parameters_json=payload.model_dump(mode="json"),
        status=CommandStatus.SUCCEEDED,
        completed_at=utcnow(),
    )
    session.add(command)
    await session.flush()
    sequence = Sequence(
        idempotency_key=idempotency_key,
        target_name=payload.target_name,
        mode=payload.mode,
        exposure_time=payload.exposure_time,
        repeats=payload.repeats,
        expected_exposures=validation.estimated_exposures,
        status=SequenceStatus.VALIDATED,
        config_snapshot_id=snapshot.id,
        created_by=user.subject,
    )
    session.add(sequence)
    await session.flush()
    await record_audit(
        session,
        user,
        action="sequence.create",
        resource_type="Sequence",
        resource_id=sequence.id,
        correlation_id=_correlation(request),
        after={"mode": sequence.mode, "target": sequence.target_name},
    )
    return CommandAccepted(
        command_id=UUID(command.id),
        resource_id=UUID(sequence.id),
        status=CommandStatus.SUCCEEDED,
    )


@router.get("/api/v1/sequences", response_model=list[SequenceRead])
async def list_sequences(
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(current_user),
) -> list[Sequence]:
    return list(
        (
            await session.scalars(
                select(Sequence).order_by(Sequence.created_at.desc()).limit(limit)
            )
        ).all()
    )


@router.get("/api/v1/sequences/{sequence_id}", response_model=SequenceRead)
async def get_sequence(
    sequence_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> Sequence:
    sequence = await session.get(Sequence, str(sequence_id))
    if sequence is None:
        raise SpriteError("SEQUENCE_NOT_FOUND", "sequence does not exist", status_code=404)
    return sequence


@router.get("/api/v1/sequences/{sequence_id}/exposures", response_model=list[ExposureRead])
async def list_exposures(
    sequence_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[Exposure]:
    return list(
        (
            await session.scalars(
                select(Exposure)
                .where(Exposure.sequence_id == str(sequence_id))
                .order_by(Exposure.sub_index)
            )
        ).all()
    )


@router.post(
    "/api/v1/sequences/{sequence_id}:{action}", status_code=202, response_model=CommandAccepted
)
async def sequence_action(
    sequence_id: UUID,
    action: Literal["start", "pause", "resume", "abort"],
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.OBSERVER, Role.INSTRUMENT_ENGINEER)),
) -> CommandAccepted:
    sequence = await session.scalar(
        select(Sequence).where(Sequence.id == str(sequence_id)).with_for_update()
    )
    if sequence is None:
        raise SpriteError("SEQUENCE_NOT_FOUND", "sequence does not exist", status_code=404)
    existing = await session.scalar(
        select(Command).where(
            Command.idempotency_key == f"api-sequence:{sequence_id}:{action}:{idempotency_key}"
        )
    )
    if existing is not None:
        return CommandAccepted(
            command_id=UUID(existing.id),
            resource_id=sequence_id,
            status=CommandStatus(existing.status),
        )
    transitions = {
        "start": ({SequenceStatus.VALIDATED}, SequenceStatus.QUEUED),
        "pause": ({SequenceStatus.QUEUED, SequenceStatus.RUNNING}, SequenceStatus.PAUSING),
        "resume": ({SequenceStatus.PAUSED, SequenceStatus.FAILED}, SequenceStatus.QUEUED),
        "abort": (
            {
                SequenceStatus.QUEUED,
                SequenceStatus.RUNNING,
                SequenceStatus.PAUSING,
                SequenceStatus.PAUSED,
            },
            SequenceStatus.ABORTING,
        ),
    }
    allowed, target = transitions[action]
    current = SequenceStatus(sequence.status)
    if current not in allowed:
        raise SpriteError(
            "INVALID_SEQUENCE_TRANSITION",
            f"cannot {action} a sequence in {current.value}",
            status_code=409,
        )
    if action == "resume" and current == SequenceStatus.FAILED:
        instrument = await session.get(InstrumentStateRecord, 1)
        assert instrument is not None
        if InstrumentState(instrument.state) == InstrumentState.SAFE_FAULT:
            raise SpriteError(
                "SAFE_FAULT_LATCHED",
                "an instrument engineer must recover the instrument before retrying the sequence",
                status_code=409,
            )
        sequence.attempt += 1
    command = Command(
        idempotency_key=f"api-sequence:{sequence_id}:{action}:{idempotency_key}",
        sequence_id=sequence.id,
        device_id="sprite-control",
        command_type=action.upper(),
        parameters_json={"sequence_id": sequence.id},
        status=CommandStatus.ACCEPTED,
    )
    session.add(command)
    sequence.status = target
    sequence.updated_at = utcnow()
    if action == "abort" and current == SequenceStatus.PAUSED:
        sequence.status = SequenceStatus.ABORTED
        command.status = CommandStatus.SUCCEEDED
        command.completed_at = utcnow()
    await emit_event(
        session,
        EventType.SEQUENCE_STATE_CHANGED,
        correlation_id=sequence.id,
        causation_id=command.id,
        sequence_id=sequence.id,
        config_snapshot_id=sequence.config_snapshot_id,
        payload={"status": sequence.status, "requested_action": action},
    )
    await record_audit(
        session,
        user,
        action=f"sequence.{action}",
        resource_type="Sequence",
        resource_id=sequence.id,
        correlation_id=_correlation(request),
        before={"status": current.value},
        after={"status": sequence.status},
    )
    await session.flush()
    return CommandAccepted(
        command_id=UUID(command.id), resource_id=sequence_id, status=CommandStatus(command.status)
    )


@router.get("/api/v1/instrument/state", response_model=InstrumentSnapshot)
async def instrument_state(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> InstrumentSnapshot:
    record = await session.get(InstrumentStateRecord, 1)
    assert record is not None
    observed = record.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    snapshot = await active_config(session)
    stale_seconds = float(snapshot.payload_json["qc"]["stale_state_seconds"])
    fresh = (datetime.now(UTC) - observed).total_seconds() <= stale_seconds
    return InstrumentSnapshot(
        state=InstrumentState(record.state),
        target_state=InstrumentState(record.target_state) if record.target_state else None,
        observed_at=observed,
        fresh=fresh,
        fencing_token=record.fencing_token,
        devices=record.devices_json,
    )


@router.post("/api/v1/instrument:recover", status_code=202, response_model=CommandAccepted)
async def instrument_recover(
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.INSTRUMENT_ENGINEER)),
) -> CommandAccepted:
    existing = await session.scalar(
        select(Command).where(Command.idempotency_key == f"api-recover:{idempotency_key}")
    )
    if existing:
        return CommandAccepted(command_id=UUID(existing.id), status=CommandStatus(existing.status))
    await recover_instrument()
    command = Command(
        idempotency_key=f"api-recover:{idempotency_key}",
        device_id="sprite-control",
        command_type="RECOVER",
        status=CommandStatus.SUCCEEDED,
        completed_at=utcnow(),
    )
    session.add(command)
    await record_audit(
        session,
        user,
        action="instrument.recover",
        resource_type="Instrument",
        correlation_id=_correlation(request),
    )
    await session.flush()
    return CommandAccepted(command_id=UUID(command.id), status=CommandStatus.SUCCEEDED)


@router.post("/sim/v1/faults/{fault_type}", status_code=202, response_model=CommandAccepted)
async def inject_fault(
    fault_type: str,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    active: bool = True,
    user: CurrentUser = Depends(require_roles(Role.INSTRUMENT_ENGINEER)),
) -> CommandAccepted:
    if get_settings().app_env != "simulation":
        raise SpriteError("SIMULATION_ONLY", "fault injection is disabled", status_code=404)
    scoped_key = f"sim-fault:{fault_type.upper()}:{active}:{idempotency_key}"
    existing = await session.scalar(select(Command).where(Command.idempotency_key == scoped_key))
    if existing is not None:
        return CommandAccepted(command_id=UUID(existing.id), status=CommandStatus(existing.status))
    feedback = await request.app.state.runtime.device.inject_fault(fault_type, active)
    command = Command(
        idempotency_key=scoped_key,
        device_id="device-agent-sim",
        command_type="INJECT_FAULT",
        parameters_json={
            "fault_type": fault_type.upper(),
            "active": active,
            "_result": feedback.model_dump(mode="json"),
        },
        status=feedback.status,
        completed_at=feedback.completed_at,
        error_code=feedback.error_code,
        error_message=feedback.error_message,
    )
    session.add(command)
    await session.flush()
    await record_audit(
        session,
        user,
        action="simulation.fault.inject",
        resource_type="DeviceSimulator",
        resource_id=command.id,
        correlation_id=_correlation(request),
        after={"fault_type": fault_type.upper(), "active": active},
    )
    return CommandAccepted(command_id=UUID(command.id), status=CommandStatus(command.status))


@router.get("/api/v1/processing-runs", response_model=list[ProcessingRunRead])
async def list_processing_runs(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[ProcessingRun]:
    return list(
        (
            await session.scalars(
                select(ProcessingRun).order_by(ProcessingRun.created_at.desc()).limit(200)
            )
        ).all()
    )


@router.get("/api/v1/import-inspections", response_model=list[ImportInspectionRead])
async def list_import_inspections(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[ImportInspection]:
    return list(
        (
            await session.scalars(
                select(ImportInspection).order_by(ImportInspection.created_at.desc()).limit(100)
            )
        ).all()
    )


@router.post(
    "/api/v1/import-inspections", status_code=202, response_model=ImportInspectionRead
)
async def create_import_inspection(
    payload: ImportInspectionRequest,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.DATA_REDUCER)),
) -> ImportInspection:
    inspection = await inspect_import_directory(
        session,
        idempotency_key=f"inspection:{idempotency_key}",
        root_id=payload.root_id,
        relative_path=payload.relative_path,
        instrument=payload.instrument,
        created_by=user.subject,
    )
    await record_audit(
        session,
        user,
        action="import.inspect",
        resource_type="ImportInspection",
        resource_id=inspection.id,
        correlation_id=_correlation(request),
        after={"root_id": payload.root_id, "status": inspection.status},
    )
    return inspection


@router.get(
    "/api/v1/import-inspections/{inspection_id}", response_model=ImportInspectionRead
)
async def get_import_inspection(
    inspection_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> ImportInspection:
    inspection = await session.get(ImportInspection, str(inspection_id))
    if inspection is None:
        raise SpriteError(
            "IMPORT_INSPECTION_NOT_FOUND", "inspection does not exist", status_code=404
        )
    return inspection


@router.get("/api/v1/imports", response_model=list[ImportBatchRead])
async def list_imports(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[ImportBatch]:
    return list(
        (
            await session.scalars(
                select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100)
            )
        ).all()
    )


@router.post("/api/v1/imports", status_code=202, response_model=ImportBatchRead)
async def create_import(
    payload: ImportCommitRequest,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.DATA_REDUCER)),
) -> ImportBatch:
    batch = await commit_import(
        session,
        inspection_id=str(payload.inspection_id),
        manifest_sha256=payload.manifest_sha256,
        idempotency_key=idempotency_key,
        created_by=user.subject,
    )
    await record_audit(
        session,
        user,
        action="import.commit",
        resource_type="ImportBatch",
        resource_id=batch.id,
        correlation_id=_correlation(request),
        after={"status": batch.status, "sequence_ids": batch.sequence_ids_json},
    )
    return batch


@router.get("/api/v1/imports/{import_id}", response_model=ImportBatchRead)
async def get_import(
    import_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> ImportBatch:
    batch = await session.get(ImportBatch, str(import_id))
    if batch is None:
        raise SpriteError("IMPORT_NOT_FOUND", "import batch does not exist", status_code=404)
    return batch


@router.get("/api/v1/calibration-runs", response_model=list[CalibrationRunRead])
async def list_calibration_runs(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[CalibrationRun]:
    return list(
        (
            await session.scalars(
                select(CalibrationRun).order_by(CalibrationRun.created_at.desc()).limit(100)
            )
        ).all()
    )


@router.post("/api/v1/calibration-runs", status_code=202, response_model=CalibrationRunRead)
async def create_calibration_run(
    payload: CalibrationRunRequest,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.DATA_REDUCER)),
) -> CalibrationRun:
    run = await ensure_calibration_run(
        session,
        import_batch_id=str(payload.import_batch_id),
        idempotency_key=f"calibration:{idempotency_key}",
        parameter_version=payload.parameter_version,
        created_by=user.subject,
    )
    await record_audit(
        session,
        user,
        action="calibration_run.create",
        resource_type="CalibrationRun",
        resource_id=run.id,
        correlation_id=_correlation(request),
        after={"import_batch_id": run.import_batch_id, "status": run.status},
    )
    return run


@router.get("/api/v1/calibration-runs/{run_id}", response_model=CalibrationRunRead)
async def get_calibration_run(
    run_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> CalibrationRun:
    run = await session.get(CalibrationRun, str(run_id))
    if run is None:
        raise SpriteError(
            "CALIBRATION_RUN_NOT_FOUND", "calibration run does not exist", status_code=404
        )
    return run


@router.get("/api/v1/calibration-sets", response_model=list[CalibrationSetRead])
async def list_calibration_sets(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[CalibrationSet]:
    return list(
        (
            await session.scalars(
                select(CalibrationSet).order_by(CalibrationSet.created_at.desc()).limit(100)
            )
        ).all()
    )


@router.get("/api/v1/calibration-sets/{set_id}", response_model=CalibrationSetRead)
async def get_calibration_set(
    set_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> CalibrationSet:
    calibration_set = await session.get(CalibrationSet, str(set_id))
    if calibration_set is None:
        raise SpriteError(
            "CALIBRATION_SET_NOT_FOUND", "calibration set does not exist", status_code=404
        )
    return calibration_set


@router.post(
    "/api/v1/calibration-sets/{set_id}/approve",
    status_code=202,
    response_model=CalibrationSetRead,
)
async def approve_calibration(
    set_id: UUID,
    payload: CalibrationSetApproval,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.ADMINISTRATOR)),
) -> CalibrationSet | dict[str, Any]:
    idempotency_payload = {
        "calibration_set_id": str(set_id),
        **payload.model_dump(mode="json"),
    }
    existing = await find_idempotent_resource(
        session,
        scope="calibration-set-approve",
        principal=user.subject,
        key=idempotency_key,
        payload=idempotency_payload,
    )
    if existing is not None:
        calibration_set = await session.get(CalibrationSet, existing.resource_id)
        if calibration_set is None:
            raise SpriteError(
                "IDEMPOTENCY_RESOURCE_GONE",
                "the resource recorded for this request no longer exists",
                status_code=410,
            )
        return calibration_set
    before = await session.get(CalibrationSet, str(set_id))
    before_status = before.status if before is not None else None
    calibration_set = await approve_calibration_set(
        session,
        calibration_set_id=str(set_id),
        approved_by=user.subject,
        reason=payload.reason,
        accept_warnings=payload.accept_warnings,
    )
    await record_audit(
        session,
        user,
        action="calibration_set.approve",
        resource_type="CalibrationSet",
        resource_id=calibration_set.id,
        reason=payload.reason,
        correlation_id=_correlation(request),
        before={"status": before_status},
        after={
            "status": calibration_set.status,
            "accepted_warnings": payload.accept_warnings,
        },
    )
    await bind_idempotent_resource(
        session,
        scope="calibration-set-approve",
        principal=user.subject,
        key=idempotency_key,
        payload=idempotency_payload,
        resource_type="CalibrationSet",
        resource_id=calibration_set.id,
    )
    return calibration_set


@router.post("/api/v1/processing-runs", status_code=202)
async def create_processing_run(
    payload: ProcessingRunRequest,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.DATA_REDUCER)),
) -> dict[str, Any]:
    idempotency_payload = payload.model_dump(mode="json")
    existing = await find_idempotent_resource(
        session,
        scope="processing-run-create",
        principal=user.subject,
        key=idempotency_key,
        payload=idempotency_payload,
    )
    if existing is not None:
        run = await session.get(ProcessingRun, existing.resource_id)
        if run is None:
            raise SpriteError(
                "IDEMPOTENCY_RESOURCE_GONE",
                "the resource recorded for this request no longer exists",
                status_code=410,
            )
        return {"processing_run_id": run.id, "status": run.status}
    run = await ensure_processing_run(
        session,
        str(payload.sequence_id),
        parameters=payload.parameters,
        calibration_set_id=(
            str(payload.calibration_set_id) if payload.calibration_set_id else None
        ),
        parameter_version=payload.parameter_version,
    )
    if run is None:
        raise SpriteError(
            "PROCESSING_INPUT_INCOMPLETE",
            "sequence does not yet have its complete immutable L0 set",
            status_code=409,
        )
    await record_audit(
        session,
        user,
        action="processing.create",
        resource_type="ProcessingRun",
        resource_id=run.id,
        correlation_id=_correlation(request),
    )
    await bind_idempotent_resource(
        session,
        scope="processing-run-create",
        principal=user.subject,
        key=idempotency_key,
        payload=idempotency_payload,
        resource_type="ProcessingRun",
        resource_id=run.id,
    )
    return {"processing_run_id": run.id, "status": run.status}


@router.get("/api/v1/processing-runs/{run_id}", response_model=ProcessingRunRead)
async def get_processing_run(
    run_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> ProcessingRun:
    run = await session.get(ProcessingRun, str(run_id))
    if run is None:
        raise SpriteError(
            "PROCESSING_RUN_NOT_FOUND", "processing run does not exist", status_code=404
        )
    return run


@router.get("/api/v1/processing-runs/{run_id}/tasks")
async def list_processing_tasks(
    run_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[dict[str, Any]]:
    tasks = (
        await session.scalars(
            select(TaskRun)
            .where(TaskRun.processing_run_id == str(run_id))
            .order_by(TaskRun.created_at)
        )
    ).all()
    return [
        {
            "id": task.id,
            "task_name": task.task_name,
            "status": task.status,
            "metrics": task.metrics_json,
            "error": task.error_json,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
        for task in tasks
    ]


@router.get("/api/v1/products", response_model=list[ProductRead])
async def list_products(
    session: SessionDep,
    sequence_id: UUID | None = None,
    level: ProductLevel | None = None,
    _: CurrentUser = Depends(current_user),
) -> list[Product]:
    statement = select(Product).order_by(Product.created_at.desc()).limit(500)
    if sequence_id:
        statement = statement.where(Product.sequence_id == str(sequence_id))
    if level:
        statement = statement.where(Product.level == level)
    return list((await session.scalars(statement)).all())


@router.get("/api/v1/products/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> Product:
    product = await session.get(Product, str(product_id))
    if product is None:
        raise SpriteError("PRODUCT_NOT_FOUND", "product does not exist", status_code=404)
    return product


@router.get("/api/v1/products/{product_id}/download", response_class=FileResponse)
async def download_product(
    product_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> FileResponse:
    product = await session.get(Product, str(product_id))
    if product is None:
        raise SpriteError("PRODUCT_NOT_FOUND", "product does not exist", status_code=404)
    path = Path(product.uri).resolve()
    data_root = get_settings().data_root.resolve()
    if data_root not in path.parents or not path.is_file():
        raise SpriteError(
            "PRODUCT_STORAGE_INVALID",
            "the immutable product is unavailable from managed storage",
            status_code=410,
        )
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/fits" if path.suffix.lower() == ".fits" else None,
    )


@router.get("/api/v1/products/{product_id}/qc")
async def product_qc(
    product_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[dict[str, Any]]:
    if await session.get(Product, str(product_id)) is None:
        raise SpriteError("PRODUCT_NOT_FOUND", "product does not exist", status_code=404)
    results = (
        await session.scalars(
            select(QCResult).where(QCResult.product_id == str(product_id)).order_by(QCResult.metric)
        )
    ).all()
    return [
        {
            "id": result.id,
            "metric": result.metric,
            "value": result.value,
            "threshold": result.threshold,
            "passed": result.passed,
            "reason_code": result.reason_code,
            "details": result.details_json,
        }
        for result in results
    ]


@router.get("/api/v1/products/{product_id}/lineage")
async def product_lineage(
    product_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    root = await session.get(Product, str(product_id))
    if root is None:
        raise SpriteError("PRODUCT_NOT_FOUND", "product does not exist", status_code=404)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    async def visit(product: Product) -> None:
        if product.id in nodes:
            return
        nodes[product.id] = {
            "id": product.id,
            "kind": "PRODUCT",
            "level": product.level,
            "schema_version": product.schema_version,
            "sha256": product.sha256,
            "qc_flag": product.qc_flag,
            "download_url": product.download_url,
        }
        inputs = (
            await session.scalars(
                select(ProductInput)
                .where(ProductInput.product_id == product.id)
                .order_by(ProductInput.id)
            )
        ).all()
        for item in inputs:
            edges.append(
                {
                    "source": item.input_id,
                    "target": product.id,
                    "relation": item.input_kind,
                    "checksum": item.input_checksum,
                }
            )
            if item.input_kind == "PRODUCT":
                parent = await session.get(Product, item.input_id)
                if parent is not None:
                    await visit(parent)
            elif item.input_kind == "RAW_FILE":
                raw = await session.get(RawFile, item.input_id)
                if raw is not None:
                    nodes[raw.id] = {
                        "id": raw.id,
                        "kind": "RAW_FILE",
                        "level": "L0",
                        "sha256": raw.sha256,
                        "exposure_id": raw.exposure_id,
                    }

    await visit(root)
    return {"root_id": root.id, "nodes": list(nodes.values()), "edges": edges}


def _finite_list(values: np.ndarray) -> list[float | None]:
    return [float(value) if np.isfinite(value) else None for value in values]


@router.get("/api/v1/products/{product_id}/preview")
async def product_preview(
    product_id: UUID, session: SessionDep, _: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    product = await session.get(Product, str(product_id))
    if product is None:
        raise SpriteError("PRODUCT_NOT_FOUND", "product does not exist", status_code=404)
    path = Path(product.uri)
    if product.level == ProductLevel.QUICKLOOK:
        return {"product_id": product.id, "level": product.level, **json.loads(path.read_text())}
    with fits.open(path, checksum=True, memmap=False) as hdul:
        if "SPECTRUM" in hdul:
            table = hdul["SPECTRUM"].data
        elif len(hdul) > 1 and isinstance(hdul[1], fits.BinTableHDU):
            table = hdul[1].data
        else:
            image = np.asarray(hdul["SCI"].data if "SCI" in hdul else hdul[0].data)
            return {
                "product_id": product.id,
                "level": product.level,
                "shape": list(image.shape),
                "minimum": float(np.nanmin(image)),
                "maximum": float(np.nanmax(image)),
                "median": float(np.nanmedian(image)),
            }
        step = max(1, len(table) // 1200)
        names = list(table.names)
        columns = {
            name: _finite_list(np.asarray(table[name][::step], dtype=np.float64))
            for name in names
            if np.issubdtype(np.asarray(table[name]).dtype, np.number)
        }
        return {
            "product_id": product.id,
            "level": product.level,
            "mode": product.mode,
            "columns": columns,
            "metadata": product.metadata_json,
        }


@router.post(
    "/api/v1/products/{product_id}:{action}",
    status_code=202,
    response_model=ProductRead,
)
async def product_action(
    product_id: UUID,
    action: Literal["publish", "withdraw"],
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    payload: ProductPublicationRequest | None = None,
    user: CurrentUser = Depends(require_roles(Role.ADMINISTRATOR)),
) -> Product | dict[str, Any]:
    reason = payload.reason if payload is not None else None
    idempotency_payload = {
        "product_id": str(product_id),
        "action": action,
        "reason": reason,
    }
    existing = await find_idempotent_resource(
        session,
        scope="product-publication",
        principal=user.subject,
        key=idempotency_key,
        payload=idempotency_payload,
    )
    if existing is not None:
        product = await session.get(Product, existing.resource_id)
        if product is None:
            raise SpriteError(
                "IDEMPOTENCY_RESOURCE_GONE",
                "the resource recorded for this request no longer exists",
                status_code=410,
            )
        return product
    product = await session.scalar(
        select(Product).where(Product.id == str(product_id)).with_for_update()
    )
    if product is None:
        raise SpriteError("PRODUCT_NOT_FOUND", "product does not exist", status_code=404)
    if product.qc_flag == QCFlag.SIMULATION_ONLY or product.metadata_json.get(
        "simulation_only", True
    ):
        raise SpriteError(
            "SIMULATION_PUBLICATION_DISABLED",
            "simulation-only products cannot be published or withdrawn",
            status_code=409,
        )
    before = product.publication_status
    if action == "publish":
        if product.level != ProductLevel.L3:
            raise SpriteError(
                "PUBLICATION_LEVEL_FORBIDDEN", "only immutable L3 variants are publishable"
            )
        if product.qc_flag == QCFlag.FAIL:
            raise SpriteError(
                "PRODUCT_QC_FAILED", "a QC FAIL product cannot be published", status_code=409
            )
        calibration_set = (
            await session.get(CalibrationSet, product.calibration_set_id)
            if product.calibration_set_id
            else None
        )
        if (
            calibration_set is None
            or calibration_set.status != ConfigurationStatus.APPROVED
        ):
            raise SpriteError(
                "CALIBRATION_NOT_APPROVED",
                "publication requires an approved CalibrationSet",
                status_code=409,
            )
        if product.qc_flag == QCFlag.WARNING and not reason:
            raise SpriteError(
                "PRODUCT_WARNING_REASON_REQUIRED",
                "publishing a WARNING product requires a recorded reason",
                status_code=409,
            )
        product.publication_status = PublicationStatus.PUBLISHED
        product.published_by = user.subject
        product.published_at = utcnow()
    else:
        if not reason:
            raise SpriteError(
                "WITHDRAWAL_REASON_REQUIRED",
                "withdrawing a product requires a recorded reason",
                status_code=422,
            )
        product.publication_status = PublicationStatus.WITHDRAWN
        product.published_by = user.subject
        product.published_at = utcnow()
    await emit_event(
        session,
        EventType.PRODUCT_PUBLICATION_CHANGED,
        correlation_id=product.id,
        sequence_id=product.sequence_id,
        payload={
            "product_id": product.id,
            "publication_status": product.publication_status,
            "reason": reason,
        },
    )
    await record_audit(
        session,
        user,
        action=f"product.{action}",
        resource_type="Product",
        resource_id=product.id,
        reason=reason,
        correlation_id=_correlation(request),
        before={"publication_status": before},
        after={"publication_status": product.publication_status},
    )
    await bind_idempotent_resource(
        session,
        scope="product-publication",
        principal=user.subject,
        key=idempotency_key,
        payload=idempotency_payload,
        resource_type="Product",
        resource_id=product.id,
    )
    return product


@router.get("/api/v1/calibrations", response_model=list[CalibrationRead])
async def list_calibrations(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[Calibration]:
    return list(
        (await session.scalars(select(Calibration).order_by(Calibration.created_at.desc()))).all()
    )


@router.post("/api/v1/calibrations", status_code=202, response_model=CommandAccepted)
async def register_calibration(
    payload: CalibrationCreate,
    request: Request,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    user: CurrentUser = Depends(require_roles(Role.DATA_REDUCER)),
) -> CommandAccepted:
    scoped_key = f"api-calibration:{idempotency_key}"
    existing = await session.scalar(select(Command).where(Command.idempotency_key == scoped_key))
    if existing is not None:
        resource_id = existing.parameters_json.get("_resource_id")
        return CommandAccepted(
            command_id=UUID(existing.id),
            resource_id=UUID(resource_id) if resource_id else None,
            status=CommandStatus(existing.status),
        )
    calibration = Calibration(
        calibration_type=payload.calibration_type,
        mode=payload.mode,
        uri=payload.uri,
        checksum=payload.checksum,
        status=ConfigurationStatus.UNVERIFIED,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        parameters_json=payload.parameters,
    )
    session.add(calibration)
    await session.flush()
    command = Command(
        idempotency_key=scoped_key,
        device_id="api",
        command_type="REGISTER_CALIBRATION",
        parameters_json={
            **payload.model_dump(mode="json"),
            "_resource_id": calibration.id,
        },
        status=CommandStatus.SUCCEEDED,
        completed_at=utcnow(),
    )
    session.add(command)
    await session.flush()
    await record_audit(
        session,
        user,
        action="calibration.register",
        resource_type="Calibration",
        resource_id=calibration.id,
        correlation_id=_correlation(request),
    )
    return CommandAccepted(
        command_id=UUID(command.id),
        resource_id=UUID(calibration.id),
        status=CommandStatus.SUCCEEDED,
    )


@router.get("/api/v1/alarms")
async def list_alarms(
    session: SessionDep, _: CurrentUser = Depends(current_user)
) -> list[dict[str, Any]]:
    alarms = (
        await session.scalars(select(Alarm).order_by(Alarm.created_at.desc()).limit(100))
    ).all()
    return [
        {
            "id": item.id,
            "severity": item.severity,
            "reason_code": item.reason_code,
            "message": item.message,
            "protective_action": item.protective_action,
            "recovery_condition": item.recovery_condition,
            "acknowledged": item.acknowledged,
            "created_at": item.created_at,
        }
        for item in alarms
    ]


@router.websocket("/ws/v1/state")
async def state_stream(websocket: WebSocket, cursor: int = 0) -> None:
    authorization = websocket.headers.get("authorization", "")
    token = authorization[7:] if authorization.lower().startswith("bearer ") else None
    try:
        await authenticate_identity(
            token=token,
            x_sprite_user=websocket.headers.get("x-sprite-user"),
            x_sprite_role=websocket.headers.get("x-sprite-role"),
        )
    except SpriteError:
        await websocket.close(code=4401, reason="authentication required")
        return
    await websocket.accept()
    current = cursor
    try:
        while True:
            async with session_scope() as session:
                events = (
                    await session.scalars(
                        select(OutboxEvent)
                        .where(OutboxEvent.sequence_no > current)
                        .order_by(OutboxEvent.sequence_no)
                        .limit(100)
                    )
                ).all()
                if events:
                    for event in events:
                        current = event.sequence_no
                        await websocket.send_json(
                            {
                                "cursor": current,
                                "event_id": event.event_id,
                                "event_type": event.event_type,
                                "schema_version": event.schema_version,
                                "occurred_at": event.occurred_at.isoformat(),
                                "correlation_id": event.correlation_id,
                                "causation_id": event.causation_id,
                                "sequence_id": event.sequence_id,
                                "group_id": event.group_id,
                                "exposure_id": event.exposure_id,
                                "config_snapshot_id": event.config_snapshot_id,
                                "payload": event.payload_json,
                            }
                        )
                else:
                    await websocket.send_json(
                        {
                            "event_type": "heartbeat.v1",
                            "cursor": current,
                            "occurred_at": datetime.now(UTC).isoformat(),
                        }
                    )
            await __import__("asyncio").sleep(1.0)
    except WebSocketDisconnect:
        return
