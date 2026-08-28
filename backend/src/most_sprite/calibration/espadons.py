"""Build and approve versioned ESPaDOnS/OLAPA calibration sets."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import median_filter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.acquisition.service import sha256_file
from most_sprite.calibration.bundle import ESPaDOnSCalibrationBundle, write_calibration_bundle
from most_sprite.config import get_settings
from most_sprite.db.models import (
    Calibration,
    CalibrationRun,
    CalibrationSet,
    ImportBatch,
    ImportedArtifact,
    utcnow,
)
from most_sprite.db.session import session_scope
from most_sprite.domain.enums import (
    ConfigurationStatus,
    EventType,
    ImportStatus,
    ProcessingStatus,
    QCFlag,
)
from most_sprite.errors import SpriteError
from most_sprite.events import emit_event
from most_sprite.pipeline.echelle.espadons import (
    build_spatial_profile,
    extract_espadons_beams,
    trace_espadons_orders,
)
from most_sprite.pipeline.echelle.flat import build_flat_model
from most_sprite.pipeline.echelle.imageproc import combine_calibration
from most_sprite.pipeline.echelle.models import CalibrationFrame
from most_sprite.pipeline.instruments.espadons import ESPaDOnSAdapter
from most_sprite.pipeline.wavelength import solve_espadons_thar

_REQUIRED_COUNTS = {"BIAS": 3, "FLAT": 10, "THAR": 1, "ALIGNMENT": 1}


def _identity(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _readout_mode(header: dict[str, Any]) -> str:
    return "|".join(
        str(header.get(key, "UNKNOWN"))
        for key in ("CCDBIN1", "CCDBIN2", "AMPLIST", "EREADSPD")
    )


@dataclass(frozen=True, slots=True)
class _ArtifactInput:
    path: Path
    role: str
    sha256: str
    header: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _BuildResult:
    path: Path
    sha256: str
    calibration_hash: str
    observing_night: str
    readout_mode: str
    qc_flag: QCFlag
    qc: dict[str, Any]
    warnings: list[dict[str, Any]]
    provenance: dict[str, Any]


def _combine(
    frames: Sequence[CalibrationFrame | np.ndarray], *, kind: str
) -> CalibrationFrame:
    result = combine_calibration(
        frames,
        {
            "read_noise_e": 4.2,
            "config_version": "espadons-olapa-v1",
        },
    )
    result.provenance.update({"calibration_kind": kind, "input_count": len(frames)})
    return result


def _normalized_blaze(
    extracted: Any,
) -> dict[str, dict[int, np.ndarray]]:
    result: dict[str, dict[int, np.ndarray]] = {}
    for role, channel in extracted.channels.items():
        result[role] = {}
        for order in np.unique(channel.order):
            selection = channel.order == order
            values = np.asarray(channel.flux[selection], dtype=np.float64)
            finite = np.isfinite(values)
            fill = float(np.nanmedian(values[finite])) if finite.any() else 1.0
            values = np.where(finite, values, fill)
            smooth = median_filter(values, 101, mode="nearest")
            scale = float(np.nanmedian(smooth[smooth > 0]))
            result[role][int(order)] = smooth / scale if scale > 0 else np.ones_like(smooth)
    return result


def _build(
    artifacts: list[_ArtifactInput], parameter_version: str, output_root: Path
) -> _BuildResult:
    counts: dict[str, int] = {}
    for artifact in artifacts:
        counts[artifact.role] = counts.get(artifact.role, 0) + 1
    missing = {
        role: {"actual": counts.get(role, 0), "minimum": minimum}
        for role, minimum in _REQUIRED_COUNTS.items()
        if counts.get(role, 0) < minimum
    }
    if missing:
        raise SpriteError(
            "CALIBRATION_MISSING",
            "same-night OLAPA calibration inventory is incomplete",
            status_code=409,
            details={"missing": missing},
        )
    detectors = {str(item.header.get("DETECTOR", "")).strip().upper() for item in artifacts}
    if not detectors or any("OLAPA" not in detector for detector in detectors):
        raise SpriteError(
            "UNSUPPORTED_DETECTOR", "all calibration inputs must identify OLAPA"
        )
    nights = {str(item.header.get("DATE-OBS", "UNKNOWN"))[:10] for item in artifacts}
    readout_modes = {_readout_mode(item.header) for item in artifacts}
    if len(nights) != 1 or "UNKNOWN" in nights:
        raise SpriteError(
            "CALIBRATION_MISMATCH", "v1 calibration inputs must come from one night"
        )
    if len(readout_modes) != 1:
        raise SpriteError(
            "CALIBRATION_MISMATCH", "v1 calibration inputs must share one readout mode"
        )
    adapter = ESPaDOnSAdapter()
    by_role: dict[str, list[_ArtifactInput]] = {}
    for artifact in artifacts:
        by_role.setdefault(artifact.role, []).append(artifact)

    bias_frames = [adapter.preprocess(item.path)[0] for item in by_role["BIAS"]]
    master_bias = _combine(bias_frames, kind="MASTER_BIAS")
    del bias_frames
    flat_frames: list[CalibrationFrame | np.ndarray] = []
    for index, item in enumerate(by_role["FLAT"]):
        frame = adapter.preprocess(item.path, master_bias=master_bias.data)[0]
        flat_frames.append(frame if index == 0 else frame.data)
    master_flat = _combine(flat_frames, kind="MASTER_FLAT")
    del flat_frames
    trace_set = trace_espadons_orders(master_flat)
    flat_model = build_flat_model(master_flat, trace_set.combined)
    spatial_profile = build_spatial_profile(master_flat, trace_set)

    arc_frame, _, _ = adapter.preprocess(
        by_role["THAR"][0].path,
        master_bias=master_bias.data,
        flat_response=flat_model.response,
    )
    arc_spectra = extract_espadons_beams(arc_frame, trace_set, spatial_profile)
    wavelength = solve_espadons_thar(arc_spectra)

    alignment_frame, _, _ = adapter.preprocess(
        by_role["ALIGNMENT"][0].path,
        master_bias=master_bias.data,
        flat_response=flat_model.response,
    )
    alignment_spectra = extract_espadons_beams(
        alignment_frame, trace_set, spatial_profile
    )
    alignment_valid_fraction = float(
        np.mean(
            [
                np.mean(np.isfinite(channel.flux))
                for channel in alignment_spectra.channels.values()
            ]
        )
    )
    flat_spectra = extract_espadons_beams(master_flat, trace_set, spatial_profile)
    blaze = _normalized_blaze(flat_spectra)

    trace_rms = float(trace_set.provenance["trace_rms_pixel"])
    flat_bad_fraction = float(np.mean((flat_model.dq & (1 << 2)) != 0))
    qc_passed = (
        trace_rms <= 0.1
        and bool(wavelength.qc["passed"])
        and alignment_valid_fraction >= 0.95
    )
    warning_codes = list(wavelength.qc["warning_codes"])
    warnings: list[dict[str, Any]] = []
    if counts["FLAT"] < 20:
        warning_codes.append("FLAT_COUNT_BELOW_RECOMMENDED")
        warnings.append(
            {
                "code": "FLAT_COUNT_BELOW_RECOMMENDED",
                "actual": counts["FLAT"],
                "recommended": 20,
                "message": "CFHT recommends 20–40 flats; the accepted minimum is 10",
            }
        )
    for code in wavelength.qc["warning_codes"]:
        warnings.append({"code": code, "message": "ThAr wavelength QC warning"})
    if trace_rms > 0.1:
        warning_codes.append("TRACE_RMS_EXCEEDS_LIMIT")
    if alignment_valid_fraction < 0.95:
        warning_codes.append("ALIGNMENT_EXTRACTION_INCOMPLETE")
    qc = {
        "passed": qc_passed,
        "trace_rms_pixel": trace_rms,
        "trace_limit_pixel": 0.1,
        "flat_bad_fraction": flat_bad_fraction,
        "alignment_valid_fraction": alignment_valid_fraction,
        "calibration_counts": counts,
        "wavelength": wavelength.qc,
        "warning_codes": sorted(set(warning_codes)),
    }
    qc_flag = QCFlag.FAIL if not qc_passed else (QCFlag.WARNING if warnings else QCFlag.PASS)
    calibration_hash = _identity(
        {
            "inputs": sorted((item.role, item.sha256) for item in artifacts),
            "parameter_version": parameter_version,
            "adapter": adapter.version,
            "software_version": get_settings().software_version,
            "software_commit": get_settings().software_commit,
        }
    )
    output = output_root / calibration_hash / "espadons-olapa-calibration.fits"
    provenance = {
        "instrument": "ESPADONS",
        "detector": "OLAPA",
        "parameter_version": parameter_version,
        "adapter_version": adapter.version,
        "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
        "inputs": [
            {"role": item.role, "sha256": item.sha256, "name": item.path.name}
            for item in artifacts
        ],
        "algorithms": {
            "overscan": "espadons_olapa_preprocess_v1",
            "trace": "espadons_curved_trace_v2",
            "extraction": "espadons_optimal_extraction_v1",
            "wavelength": "espadons_thar_global_2d_v2",
        },
    }
    bundle = ESPaDOnSCalibrationBundle(
        master_bias=master_bias,
        master_flat=master_flat,
        flat_response=flat_model.response,
        flat_variance=flat_model.variance,
        flat_dq=flat_model.dq,
        spatial_profile=spatial_profile,
        trace_set=trace_set,
        wavelength_solution=wavelength.solution,
        blaze=blaze,
        identified_lines=wavelength.identified_lines,
        qc=qc,
        provenance=provenance,
    )
    write_calibration_bundle(bundle, output)
    return _BuildResult(
        path=output,
        sha256=sha256_file(output),
        calibration_hash=calibration_hash,
        observing_night=next(iter(nights)),
        readout_mode=next(iter(readout_modes)),
        qc_flag=qc_flag,
        qc=qc,
        warnings=warnings,
        provenance=provenance,
    )


async def ensure_calibration_run(
    session: AsyncSession,
    *,
    import_batch_id: str,
    idempotency_key: str,
    parameter_version: str,
    created_by: str,
) -> CalibrationRun:
    existing = await session.scalar(
        select(CalibrationRun).where(CalibrationRun.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.import_batch_id != import_batch_id
            or existing.parameter_version != parameter_version
        ):
            raise SpriteError(
                "IDEMPOTENCY_CONFLICT",
                "this Idempotency-Key was already used for a different calibration run",
                status_code=409,
            )
        return existing
    batch = await session.get(ImportBatch, import_batch_id)
    if batch is None:
        raise SpriteError("IMPORT_NOT_FOUND", "import batch does not exist", status_code=404)
    if batch.status != ImportStatus.SUCCEEDED:
        raise SpriteError(
            "IMPORT_NOT_READY", "calibration requires a committed import", status_code=409
        )
    run = CalibrationRun(
        import_batch_id=batch.id,
        idempotency_key=idempotency_key,
        status=ProcessingStatus.QUEUED,
        parameter_version=parameter_version,
        created_by=created_by,
    )
    session.add(run)
    await session.flush()
    await emit_event(
        session,
        EventType.CALIBRATION_RUN_STATE_CHANGED,
        correlation_id=run.id,
        payload={"calibration_run_id": run.id, "status": run.status},
    )
    return run


async def _record_calibration_failure(
    run_id: str,
    exc: Exception,
    *,
    fallback_code: str,
) -> None:
    code = exc.code if isinstance(exc, SpriteError) else fallback_code
    async with session_scope() as session:
        run = await session.get(CalibrationRun, run_id)
        if run is None:
            return
        run.status = (
            ProcessingStatus.WAITING_CALIBRATION
            if code == "CALIBRATION_MISSING"
            else ProcessingStatus.FAILED
        )
        run.error_code = code
        run.error_message = str(exc)
        run.updated_at = utcnow()
        await emit_event(
            session,
            EventType.CALIBRATION_RUN_STATE_CHANGED,
            correlation_id=run.id,
            payload={"calibration_run_id": run.id, "status": run.status, "error": code},
        )


async def build_calibration_run(run_id: str) -> None:
    async with session_scope() as session:
        run = await session.get(CalibrationRun, run_id)
        if run is None:
            raise ValueError(f"unknown calibration run {run_id}")
        existing = await session.scalar(
            select(CalibrationSet).where(CalibrationSet.calibration_run_id == run.id)
        )
        if existing is not None and run.status == ProcessingStatus.SUCCEEDED:
            return
        run.status = ProcessingStatus.RUNNING
        run.progress = 0.05
        run.error_code = None
        run.error_message = None
        run.updated_at = utcnow()
        artifacts = list(
            (
                await session.scalars(
                    select(ImportedArtifact)
                    .where(ImportedArtifact.import_batch_id == run.import_batch_id)
                    .order_by(ImportedArtifact.relative_path)
                )
            ).all()
        )
        inputs = [
            _ArtifactInput(
                path=Path(item.managed_uri),
                role=item.artifact_role,
                sha256=item.sha256,
                header=item.header_json,
            )
            for item in artifacts
            if item.artifact_role in _REQUIRED_COUNTS
        ]
        parameter_version = run.parameter_version
        await session.commit()
    try:
        result = await asyncio.to_thread(
            _build,
            inputs,
            parameter_version,
            get_settings().data_root / "calibrations",
        )
    except Exception as exc:
        await _record_calibration_failure(
            run_id,
            exc,
            fallback_code="CALIBRATION_BUILD_FAILED",
        )
        return

    try:
        async with session_scope() as session:
            run = await session.get(CalibrationRun, run_id)
            assert run is not None
            calibration_set = CalibrationSet(
                calibration_run_id=run.id,
                import_batch_id=run.import_batch_id,
                instrument="ESPADONS",
                detector="OLAPA",
                observing_night=result.observing_night,
                readout_mode=result.readout_mode,
                status=ConfigurationStatus.UNVERIFIED,
                calibration_hash=result.calibration_hash,
                artifact_uri=str(result.path.resolve()),
                qc_flag=result.qc_flag,
                qc_json=result.qc,
                warnings_json=result.warnings,
            )
            session.add(calibration_set)
            await session.flush()
            for calibration_type in (
                "MASTER_BIAS",
                "MASTER_FLAT",
                "TRACE_AB",
                "SPATIAL_PROFILE_AB",
                "FP_GEOMETRY",
                "THAR_WAVELENGTH_AB",
            ):
                session.add(
                    Calibration(
                        calibration_type=calibration_type,
                        uri=str(result.path.resolve()),
                        checksum=result.sha256,
                        status=ConfigurationStatus.UNVERIFIED,
                        parameters_json={
                            "instrument": "ESPADONS",
                            "detector": "OLAPA",
                            "observing_night": result.observing_night,
                            "readout_mode": result.readout_mode,
                            "parameter_version": run.parameter_version,
                        },
                        calibration_set_id=calibration_set.id,
                    )
                )
            run.status = ProcessingStatus.SUCCEEDED
            run.progress = 1.0
            run.updated_at = utcnow()
            await emit_event(
                session,
                EventType.CALIBRATION_SET_STATE_CHANGED,
                correlation_id=calibration_set.id,
                payload={
                    "calibration_run_id": run.id,
                    "calibration_set_id": calibration_set.id,
                    "status": calibration_set.status,
                    "qc_flag": calibration_set.qc_flag,
                },
            )
    except Exception as exc:
        await _record_calibration_failure(
            run_id,
            exc,
            fallback_code="CALIBRATION_PERSIST_FAILED",
        )


async def approve_calibration_set(
    session: AsyncSession,
    *,
    calibration_set_id: str,
    approved_by: str,
    reason: str,
    accept_warnings: bool,
) -> CalibrationSet:
    calibration_set = await session.scalar(
        select(CalibrationSet)
        .where(CalibrationSet.id == calibration_set_id)
        .with_for_update()
    )
    if calibration_set is None:
        raise SpriteError(
            "CALIBRATION_SET_NOT_FOUND", "calibration set does not exist", status_code=404
        )
    if calibration_set.status == ConfigurationStatus.APPROVED:
        raise SpriteError(
            "CALIBRATION_ALREADY_APPROVED",
            "an approved CalibrationSet is immutable",
            status_code=409,
        )
    if calibration_set.qc_flag == QCFlag.FAIL:
        raise SpriteError(
            "CALIBRATION_QC_FAILED", "a QC FAIL calibration set cannot be approved", status_code=409
        )
    if calibration_set.qc_flag == QCFlag.WARNING and not accept_warnings:
        raise SpriteError(
            "CALIBRATION_WARNING_ACCEPTANCE_REQUIRED",
            "approval must explicitly accept recorded warnings",
            status_code=409,
            details={"warnings": calibration_set.warnings_json},
        )
    calibration_set.status = ConfigurationStatus.APPROVED
    calibration_set.approved_by = approved_by
    calibration_set.approved_at = utcnow()
    calibration_set.approval_reason = reason
    children = list(
        (
            await session.scalars(
                select(Calibration).where(
                    Calibration.calibration_set_id == calibration_set.id
                )
            )
        ).all()
    )
    for child in children:
        child.status = ConfigurationStatus.APPROVED
    await emit_event(
        session,
        EventType.CALIBRATION_SET_STATE_CHANGED,
        correlation_id=calibration_set.id,
        payload={
            "calibration_set_id": calibration_set.id,
            "status": calibration_set.status,
            "approved_by": approved_by,
        },
    )
    return calibration_set
