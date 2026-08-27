from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC
from pathlib import Path
from uuid import uuid4

import astropy.units as u
import numpy as np
import structlog
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.time import Time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.acquisition.service import sha256_file
from most_sprite.calibration import read_calibration_bundle
from most_sprite.config import get_settings
from most_sprite.configuration import qc_configuration
from most_sprite.db.models import (
    CalibrationSet,
    ConfigSnapshot,
    Exposure,
    ImportedArtifact,
    ProcessingRun,
    Product,
    ProductInput,
    QCResult,
    RawFile,
    Sequence,
    TaskRun,
    utcnow,
)
from most_sprite.db.session import session_scope
from most_sprite.domain.enums import (
    ConfigurationStatus,
    DataMode,
    EventType,
    ExposureStatus,
    ProcessingStatus,
    ProductLevel,
    PublicationStatus,
    QCFlag,
)
from most_sprite.errors import SpriteError
from most_sprite.events import emit_event
from most_sprite.pipeline.detector import preprocess_l0
from most_sprite.pipeline.echelle.espadons import extract_espadons_beams
from most_sprite.pipeline.echelle.models import SpectrumSet
from most_sprite.pipeline.instruments.espadons import ESPaDOnSAdapter
from most_sprite.pipeline.nonpolar import subtract_sky
from most_sprite.pipeline.polarimetry import (
    BeamSpectrum,
    demodulate_group,
    demodulate_resampled_orders,
    merge_polarimetric_orders,
    normalize_stokes_intensity,
    shift_wavelength_coordinate,
)
from most_sprite.pipeline.wavelength import (
    apply_wavelength_solution,
    calibrate_simulated_thar,
    common_log_grids,
    resample_common_grid,
)
from most_sprite.products.fits_io import (
    extract_simulation_channels,
    write_l1,
    write_l2,
    write_nonpolar_l3,
    write_polar_l3,
)
from most_sprite.quicklook import create_quicklook

logger = structlog.get_logger(__name__)


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def ensure_processing_run(
    session: AsyncSession,
    sequence_id: str,
    *,
    parameters: dict | None = None,
    calibration_set_id: str | None = None,
    parameter_version: str = "simulation-v1",
) -> ProcessingRun | None:
    sequence = await session.get(Sequence, sequence_id)
    if sequence is None:
        return None
    raw_rows = (
        (
            await session.execute(
                select(RawFile)
                .join(Exposure, RawFile.exposure_id == Exposure.id)
                .where(
                    Exposure.sequence_id == sequence_id,
                    Exposure.status == ExposureStatus.COMMITTED,
                )
                .order_by(Exposure.sub_index)
            )
        )
        .scalars()
        .all()
    )
    if len(raw_rows) < sequence.expected_exposures:
        return None
    input_hash = _hash_json([row.sha256 for row in raw_rows])
    snapshot = await session.get(ConfigSnapshot, sequence.config_snapshot_id)
    if snapshot is None:
        raise ValueError("processing configuration snapshot does not exist")
    instruments = {row.instrument or "MOST" for row in raw_rows}
    is_espadons = instruments == {"ESPADONS"}
    if "ESPADONS" in instruments and not is_espadons:
        raise SpriteError(
            "PROCESSING_INPUT_MIXED",
            "real ESPaDOnS and simulation inputs cannot share a processing run",
            status_code=409,
        )
    calibration_set: CalibrationSet | None = None
    queued = True
    if is_espadons:
        if calibration_set_id is not None:
            calibration_set = await session.get(CalibrationSet, calibration_set_id)
            if calibration_set is None:
                raise SpriteError(
                    "CALIBRATION_SET_NOT_FOUND",
                    "calibration set does not exist",
                    status_code=404,
                )
        queued = bool(
            calibration_set is not None
            and calibration_set.status == ConfigurationStatus.APPROVED
            and calibration_set.qc_flag != QCFlag.FAIL
        )
        calibration_hash = (
            calibration_set.calibration_hash
            if calibration_set is not None
            else _hash_json({"selected": None, "policy": "REQUIRED_FOR_ESPADONS"})
        )
        if parameter_version == "simulation-v1":
            parameter_version = "espadons-olapa-v1"
    else:
        if calibration_set_id is not None:
            raise SpriteError(
                "CALIBRATION_MISMATCH",
                "simulation sequences cannot consume a real CalibrationSet",
                status_code=409,
            )
        calibration_hash = _hash_json(
            {"selected": [], "policy": "SIMULATION_NO_FORMAL_CALIBRATIONS"}
        )
    parameter_hash = _hash_json(
        {
            "config_content_hash": snapshot.content_hash,
            "parameters": parameters or {},
            "parameter_version": parameter_version,
            "science_schema": 2,
        }
    )
    settings = get_settings()
    code_hash = _hash_json(
        {"version": settings.software_version, "commit": settings.software_commit}
    )
    existing = await session.scalar(
        select(ProcessingRun).where(
            ProcessingRun.input_hash == input_hash,
            ProcessingRun.calibration_hash == calibration_hash,
            ProcessingRun.parameter_hash == parameter_hash,
            ProcessingRun.code_hash == code_hash,
        )
    )
    if existing is not None:
        if queued and existing.status == ProcessingStatus.WAITING_CALIBRATION:
            existing.status = ProcessingStatus.QUEUED
            existing.calibration_set_id = calibration_set.id if calibration_set else None
            existing.error_code = None
            existing.error_message = None
            existing.updated_at = utcnow()
            await emit_event(
                session,
                EventType.PROCESSING_RUN_STATE_CHANGED,
                correlation_id=sequence_id,
                sequence_id=sequence_id,
                payload={"processing_run_id": existing.id, "status": existing.status},
            )
        return existing
    run = ProcessingRun(
        sequence_id=sequence_id,
        status=(
            ProcessingStatus.QUEUED
            if queued
            else ProcessingStatus.WAITING_CALIBRATION
        ),
        input_hash=input_hash,
        calibration_hash=calibration_hash,
        parameter_hash=parameter_hash,
        code_hash=code_hash,
        calibration_set_id=calibration_set.id if calibration_set else None,
        parameter_version=parameter_version,
        parameters_json=parameters or {},
    )
    session.add(run)
    await session.flush()
    await emit_event(
        session,
        EventType.PROCESSING_RUN_STATE_CHANGED,
        correlation_id=sequence_id,
        sequence_id=sequence_id,
        payload={"processing_run_id": run.id, "status": run.status},
    )
    return run


def _science_product_hash(run: ProcessingRun, task: str, inputs: list[str]) -> str:
    return _hash_json(
        {
            "task": task,
            "inputs": inputs,
            "calibration_hash": run.calibration_hash,
            "parameter_hash": run.parameter_hash,
            "code_hash": run.code_hash,
        }
    )


async def _register_product(
    session: AsyncSession,
    *,
    run: ProcessingRun | None,
    sequence: Sequence,
    exposure_id: str | None,
    level: ProductLevel,
    mode: DataMode,
    path: Path,
    product_hash: str,
    schema_version: str,
    metadata: dict,
    inputs: list[tuple[str, str, str]],
    simulation: bool = True,
    instrument: str | None = None,
    detector_profile: str | None = None,
    import_batch_id: str | None = None,
    calibration_set_id: str | None = None,
    qc_flag: QCFlag = QCFlag.SIMULATION_ONLY,
) -> Product:
    existing = await session.scalar(select(Product).where(Product.product_hash == product_hash))
    if existing is not None:
        return existing
    digest = sha256_file(path)
    product = Product(
        processing_run_id=run.id if run else None,
        sequence_id=sequence.id,
        exposure_id=exposure_id,
        level=level,
        mode=mode,
        uri=str(path.resolve()),
        size=path.stat().st_size,
        sha256=digest,
        product_hash=product_hash,
        schema_version=schema_version,
        qc_flag=qc_flag if not simulation else QCFlag.SIMULATION_ONLY,
        metadata_json={
            **metadata,
            **(
                {
                    "processing_identity": {
                        "input_hash": run.input_hash,
                        "calibration_hash": run.calibration_hash,
                        "parameter_hash": run.parameter_hash,
                        "code_hash": run.code_hash,
                    }
                }
                if run
                else {}
            ),
            "simulation_only": simulation,
            "publishable": not simulation and qc_flag != QCFlag.FAIL,
        },
        instrument=instrument,
        detector_profile=detector_profile,
        import_batch_id=import_batch_id,
        calibration_set_id=calibration_set_id,
        publication_status=PublicationStatus.DRAFT,
    )
    session.add(product)
    await session.flush()
    for input_id, input_kind, checksum in inputs:
        session.add(
            ProductInput(
                product_id=product.id,
                input_id=input_id,
                input_kind=input_kind,
                input_checksum=checksum,
            )
        )
    return product


async def ensure_quicklook_for_exposure(session: AsyncSession, exposure_id: str) -> Product | None:
    exposure = await session.get(Exposure, exposure_id)
    if exposure is None or not exposure.raw_file_id:
        return None
    raw = await session.get(RawFile, exposure.raw_file_id)
    sequence = await session.get(Sequence, exposure.sequence_id)
    if raw is None or sequence is None:
        return None
    config = await session.get(ConfigSnapshot, sequence.config_snapshot_id)
    if config is None:
        return None
    product_hash = _hash_json({"raw": raw.sha256, "task": "quicklook-v1"})
    existing = await session.scalar(select(Product).where(Product.product_hash == product_hash))
    if existing is not None:
        return existing
    output = get_settings().data_root / "quicklook" / sequence.id / f"{exposure.id}.json"
    saturation_adu = float(config.payload_json["detector"]["saturation_adu"])
    metrics = create_quicklook(Path(raw.uri), output, saturation_adu=saturation_adu)
    return await _register_product(
        session,
        run=None,
        sequence=sequence,
        exposure_id=exposure.id,
        level=ProductLevel.QUICKLOOK,
        mode=DataMode(sequence.mode),
        path=output,
        product_hash=product_hash,
        schema_version="QL-v1",
        metadata=metrics,
        inputs=[(raw.id, "RAW_FILE", raw.sha256)],
    )


async def _import_batch_id(
    session: AsyncSession, rows: list[tuple[Exposure, RawFile]]
) -> str | None:
    artifact_id = next(
        (raw.imported_artifact_id for _, raw in rows if raw.imported_artifact_id), None
    )
    if artifact_id is None:
        return None
    artifact = await session.get(ImportedArtifact, artifact_id)
    return artifact.import_batch_id if artifact is not None else None


def _heliocentric_velocity(
    rows: list[tuple[Exposure, RawFile]], headers: list[dict[str, object]]
) -> tuple[float, dict[str, object]]:
    header = headers[0]
    ra_value = header.get("RA_DEG") or header.get("OBJRA") or header.get("RA")
    dec_value = header.get("DEC_DEG") or header.get("OBJDEC") or header.get("DEC")
    if ra_value is None or dec_value is None:
        raise SpriteError(
            "HELIOCENTRIC_COORDINATES_MISSING",
            "RA and DEC are required for the HELIOCEN L3 variants",
        )
    if isinstance(ra_value, str) and ":" in ra_value:
        coordinate = SkyCoord(str(ra_value), str(dec_value), unit=(u.hourangle, u.deg))
    else:
        coordinate = SkyCoord(float(str(ra_value)) * u.deg, float(str(dec_value)) * u.deg)
    midpoints: list[float] = []
    weights: list[float] = []
    for (exposure, _), input_header in zip(rows, headers, strict=True):
        exposure_time = float(str(input_header.get("EXPTIME", 0.0) or 0.0))
        if exposure.started_at is not None:
            start = exposure.started_at
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            midpoint = start.timestamp() + exposure_time / 2.0
        else:
            mjd = input_header.get("MJD-OBS") or input_header.get("MJDATE")
            if mjd is None:
                raise SpriteError(
                    "HELIOCENTRIC_TIME_MISSING",
                    "MJD-OBS or an exposure start time is required",
                )
            midpoint = Time(float(str(mjd)), format="mjd").to_datetime(
                timezone=UTC
            ).timestamp()
            midpoint += exposure_time / 2.0
        midpoints.append(midpoint)
        weights.append(max(exposure_time, 1.0))
    weighted_timestamp = float(np.average(midpoints, weights=weights))
    obstime = Time(weighted_timestamp, format="unix")
    location = EarthLocation.from_geodetic(
        lon=-155.468876 * u.deg,
        lat=19.825252 * u.deg,
        height=4204.0 * u.m,
    )
    correction = coordinate.radial_velocity_correction(
        kind="heliocentric", obstime=obstime, location=location
    )
    velocity = float(correction.to_value(u.m / u.s))
    return velocity, {
        "weighted_midpoint_utc": obstime.utc.isot,
        "ra_deg": float(coordinate.ra.deg),
        "dec_deg": float(coordinate.dec.deg),
        "observatory": "CFHT",
        "algorithm": "astropy-heliocentric-coordinate-v1",
    }


async def _process_espadons_sequence(
    session: AsyncSession,
    *,
    run: ProcessingRun,
    task: TaskRun,
    sequence: Sequence,
    mode: DataMode,
    rows: list[tuple[Exposure, RawFile]],
    root: Path,
) -> None:
    if not mode.is_polarimetric:
        raise SpriteError(
            "ESPADONS_MODE_UNSUPPORTED",
            "the v1 ESPaDOnS adapter publishes only Q, U and V sequences",
        )
    if run.calibration_set_id is None:
        raise SpriteError(
            "CALIBRATION_MISSING", "a real ESPaDOnS run requires calibration_set_id"
        )
    calibration_set = await session.get(CalibrationSet, run.calibration_set_id)
    if (
        calibration_set is None
        or calibration_set.status != ConfigurationStatus.APPROVED
        or calibration_set.qc_flag == QCFlag.FAIL
    ):
        raise SpriteError(
            "CALIBRATION_NOT_APPROVED",
            "real processing requires an approved non-failing CalibrationSet",
            status_code=409,
        )
    bundle = await asyncio.to_thread(
        read_calibration_bundle, Path(calibration_set.artifact_uri)
    )
    adapter = ESPaDOnSAdapter()
    import_batch_id = await _import_batch_id(session, rows)
    l2_outputs: list[tuple[Exposure, RawFile, SpectrumSet, Product]] = []
    source_headers: list[dict[str, object]] = []
    for index, (exposure, raw) in enumerate(rows, start=1):
        if raw.instrument != "ESPADONS" or raw.detector_profile != "OLAPA":
            raise SpriteError(
                "PROCESSING_INPUT_MISMATCH",
                "all real inputs must be ESPADONS/OLAPA",
            )
        l1_frame, header, _ = await asyncio.to_thread(
            adapter.preprocess,
            Path(raw.uri),
            master_bias=bundle.master_bias.data,
            master_bias_variance=bundle.master_bias.variance,
            flat_response=bundle.flat_response,
            flat_variance=bundle.flat_variance,
            flat_dq=bundle.flat_dq,
        )
        source_headers.append(header)
        l1_path = root / "L1" / f"{exposure.id}.fits"
        write_l1(
            l1_frame,
            l1_path,
            mode=mode,
            sequence_id=sequence.id,
            exposure_id=exposure.id,
            config_id=sequence.config_snapshot_id,
            instrument="ESPADONS",
            detector="OLAPA",
            calibration_set_id=calibration_set.id,
            calibration_version=run.parameter_version,
            modulation_version=adapter.demodulation_model(mode).version,
            qc_flag=str(calibration_set.qc_flag),
        )
        l1_hash = _science_product_hash(run, "ESPADONS-L1-v1", [raw.sha256])
        l1_product = await _register_product(
            session,
            run=run,
            sequence=sequence,
            exposure_id=exposure.id,
            level=ProductLevel.L1,
            mode=mode,
            path=l1_path,
            product_hash=l1_hash,
            schema_version="L1-v1",
            metadata=l1_frame.provenance,
            inputs=[(raw.id, "RAW_FILE", raw.sha256)],
            simulation=False,
            instrument="ESPADONS",
            detector_profile="OLAPA",
            import_batch_id=import_batch_id,
            calibration_set_id=calibration_set.id,
            qc_flag=QCFlag(calibration_set.qc_flag),
        )
        spectra = await asyncio.to_thread(
            extract_espadons_beams,
            l1_frame,
            bundle.trace_set,
            bundle.spatial_profile,
        )
        spectra = apply_wavelength_solution(spectra, bundle.wavelength_solution)
        l2_path = root / "L2" / f"{exposure.id}.fits"
        write_l2(
            spectra,
            l2_path,
            mode=mode,
            sequence_id=sequence.id,
            exposure_id=exposure.id,
            config_id=sequence.config_snapshot_id,
            instrument="ESPADONS",
            detector="OLAPA",
            calibration_set_id=calibration_set.id,
            calibration_version=run.parameter_version,
            modulation_version=adapter.demodulation_model(mode).version,
            wavelength_type="AIR",
            qc_flag=str(calibration_set.qc_flag),
        )
        l2_hash = _science_product_hash(
            run,
            "ESPADONS-L2-v1",
            [l1_product.product_hash],
        )
        l2_product = await _register_product(
            session,
            run=run,
            sequence=sequence,
            exposure_id=exposure.id,
            level=ProductLevel.L2,
            mode=mode,
            path=l2_path,
            product_hash=l2_hash,
            schema_version="L2-v1",
            metadata={
                **spectra.provenance,
                "native_grid": True,
                "wavelength_type": "AIR",
                "specsys": "TOPOCENT",
            },
            inputs=[(l1_product.id, "PRODUCT", l1_product.sha256)],
            simulation=False,
            instrument="ESPADONS",
            detector_profile="OLAPA",
            import_batch_id=import_batch_id,
            calibration_set_id=calibration_set.id,
            qc_flag=QCFlag(calibration_set.qc_flag),
        )
        l2_outputs.append((exposure, raw, spectra, l2_product))
        run.progress = 0.1 + 0.55 * index / len(rows)
        run.updated_at = utcnow()
        await session.commit()

    global_grid, grids_by_order = common_log_grids(
        [item[2] for item in l2_outputs], velocity_step_km_s=1.8
    )
    resampled = [resample_common_grid(item[2], grids_by_order) for item in l2_outputs]
    null_sigma_threshold = float(qc_configuration()["null_sigma_threshold"])
    per_order = demodulate_resampled_orders(
        resampled,
        sub_indices=[item[0].sub_index for item in l2_outputs],
        exposure_ids=[item[0].id for item in l2_outputs],
        model=adapter.demodulation_model(mode),
        null_sigma_threshold=null_sigma_threshold,
    )
    merged = merge_polarimetric_orders(per_order, global_grid, blaze=bundle.blaze)
    heliocentric_velocity, heliocentric_provenance = _heliocentric_velocity(
        rows, source_headers
    )
    normalized = normalize_stokes_intensity(merged)
    variants = {
        ("UNNORMALIZED", "TOPOCENT"): merged,
        ("NORMALIZED", "TOPOCENT"): normalized,
        (
            "UNNORMALIZED",
            "HELIOCEN",
        ): shift_wavelength_coordinate(
            merged,
            velocity_m_s=heliocentric_velocity,
            frame="HELIOCEN",
            provenance=heliocentric_provenance,
        ),
        (
            "NORMALIZED",
            "HELIOCEN",
        ): shift_wavelength_coordinate(
            normalized,
            velocity_m_s=heliocentric_velocity,
            frame="HELIOCEN",
            provenance=heliocentric_provenance,
        ),
    }
    null_p99 = np.asarray(
        [merged.qc["null1_p99_sigma"], merged.qc["null2_p99_sigma"]],
        dtype=np.float64,
    )
    null_failed = bool(
        not np.all(np.isfinite(null_p99))
        or np.any(null_p99 > null_sigma_threshold)
    )
    product_qc = (
        QCFlag.FAIL
        if null_failed
        else (
            QCFlag.WARNING
            if calibration_set.qc_flag == QCFlag.WARNING
            else QCFlag.PASS
        )
    )
    group_id = rows[0][0].group_id or "NA"
    exposure_metadata = [
        {
            "exposure_id": exposure.id,
            "sub_index": exposure.sub_index,
            "fr1_cmd": exposure.fr1_commanded,
            "fr1_meas": exposure.fr1_measured,
            "fr3_cmd": exposure.fr3_commanded,
            "fr3_meas": exposure.fr3_measured,
        }
        for exposure, _ in rows
    ]
    for (normalization, specsys), product_data in variants.items():
        variant = f"{normalization}-{specsys}"
        path = root / "L3" / f"{group_id}-{mode.value}-{variant}.fits"
        write_polar_l3(
            product_data,
            path,
            mode=mode,
            sequence_id=sequence.id,
            group_id=group_id,
            config_id=sequence.config_snapshot_id,
            exposure_rows=exposure_metadata,
            instrument="ESPADONS",
            detector="OLAPA",
            calibration_set_id=calibration_set.id,
            calibration_version=run.parameter_version,
            modulation_version=adapter.demodulation_model(mode).version,
            wavelength_type="AIR",
            specsys=specsys,
            normalization_status=normalization,
            qc_flag=str(product_qc),
        )
        product_hash = _science_product_hash(
            run,
            f"ESPADONS-POL-L3-v1:{variant}",
            [item[3].product_hash for item in l2_outputs],
        )
        product = await _register_product(
            session,
            run=run,
            sequence=sequence,
            exposure_id=None,
            level=ProductLevel.L3,
            mode=mode,
            path=path,
            product_hash=product_hash,
            schema_version="L3-v1",
            metadata={
                "group_id": group_id,
                "normalization": normalization,
                "specsys": specsys,
                "wavelength_type": "AIR",
                "polarization_continuum_removed": False,
                "heliocentric_velocity_m_s": heliocentric_velocity,
                **product_data.qc,
                "provenance": product_data.provenance,
            },
            inputs=[(item[3].id, "PRODUCT", item[3].sha256) for item in l2_outputs],
            simulation=False,
            instrument="ESPADONS",
            detector_profile="OLAPA",
            import_batch_id=import_batch_id,
            calibration_set_id=calibration_set.id,
            qc_flag=product_qc,
        )
        for metric in (
            "null1_rms",
            "null2_rms",
            "null1_max_sigma",
            "null2_max_sigma",
            "null1_p99_sigma",
            "null2_p99_sigma",
            "null1_excess_fraction",
            "null2_excess_fraction",
        ):
            value = float(product_data.qc[metric])
            threshold = null_sigma_threshold if "p99_sigma" in metric else None
            session.add(
                QCResult(
                    product_id=product.id,
                    metric=metric,
                    value=value,
                    threshold=threshold,
                    passed=threshold is None or value <= threshold,
                    reason_code=(
                        "PASS"
                        if threshold is None or value <= threshold
                        else f"{metric.upper()}_EXCESS"
                    ),
                )
            )
    task.metrics_json = {
        "l2_product_count": len(l2_outputs),
        "l3_variant_count": len(variants),
        "mode": mode.value,
        "calibration_set_id": calibration_set.id,
        "common_grid_velocity_km_s": 1.8,
    }


async def process_run(run_id: str, *, claim_token: str | None = None) -> None:
    active_claim = claim_token or str(uuid4())
    try:
        async with session_scope() as session:
            run = await session.scalar(
                select(ProcessingRun)
                .where(ProcessingRun.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise ValueError(f"unknown processing run {run_id}")
            if run.status == ProcessingStatus.SUCCEEDED:
                return
            claimed_at = run.claimed_at
            if claimed_at is not None and claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=UTC)
            claim_age = (
                (utcnow() - claimed_at).total_seconds()
                if claimed_at is not None
                else float("inf")
            )
            if (
                run.status == ProcessingStatus.RUNNING
                and run.claim_token != active_claim
                and claim_age < get_settings().processing_claim_timeout_seconds
            ):
                logger.info(
                    "processing_run_already_claimed",
                    processing_run_id=run_id,
                    claim_age_seconds=claim_age,
                )
                return
            sequence = await session.get(Sequence, run.sequence_id)
            assert sequence is not None
            mode = DataMode(sequence.mode)
            run.status = ProcessingStatus.RUNNING
            run.claim_token = active_claim
            run.claimed_at = utcnow()
            run.progress = 0.01
            run.error_code = None
            run.error_message = None
            run.updated_at = utcnow()
            await emit_event(
                session,
                EventType.PROCESSING_RUN_STATE_CHANGED,
                correlation_id=sequence.id,
                sequence_id=sequence.id,
                payload={
                    "processing_run_id": run.id,
                    "status": ProcessingStatus.RUNNING,
                    "claim_token": active_claim,
                },
            )
            task = await session.scalar(
                select(TaskRun).where(
                    TaskRun.processing_run_id == run.id,
                    TaskRun.task_name == "l0-to-l3",
                )
            )
            if task is None:
                task = TaskRun(
                    processing_run_id=run.id,
                    task_name="l0-to-l3",
                    status=ProcessingStatus.RUNNING,
                )
                session.add(task)
            else:
                task.status = ProcessingStatus.RUNNING
                task.metrics_json = {}
                task.error_json = {}
            await session.commit()

            rows = (
                await session.execute(
                    select(Exposure, RawFile)
                    .join(RawFile, RawFile.exposure_id == Exposure.id)
                    .where(Exposure.sequence_id == sequence.id)
                    .order_by(Exposure.sub_index)
                )
            ).all()
            if len(rows) != sequence.expected_exposures:
                raise ValueError("processing input set is incomplete")

            root = get_settings().data_root / "products" / sequence.id / run.id
            if {raw.instrument for _, raw in rows} == {"ESPADONS"}:
                await _process_espadons_sequence(
                    session,
                    run=run,
                    task=task,
                    sequence=sequence,
                    mode=mode,
                    rows=[(row[0], row[1]) for row in rows],
                    root=root,
                )
                run.status = ProcessingStatus.SUCCEEDED
                run.progress = 1.0
                run.updated_at = utcnow()
                task.status = ProcessingStatus.SUCCEEDED
                await emit_event(
                    session,
                    EventType.PROCESSING_RUN_STATE_CHANGED,
                    correlation_id=sequence.id,
                    sequence_id=sequence.id,
                    payload={
                        "processing_run_id": run.id,
                        "status": ProcessingStatus.SUCCEEDED,
                    },
                )
                return
            l2_outputs: list[tuple[Exposure, RawFile, SpectrumSet, Product]] = []
            for index, (exposure, raw) in enumerate(rows, start=1):
                await ensure_quicklook_for_exposure(session, exposure.id)
                l1_frame, _ = preprocess_l0(Path(raw.uri))
                l1_path = root / "L1" / f"{exposure.id}.fits"
                write_l1(
                    l1_frame,
                    l1_path,
                    mode=mode,
                    sequence_id=sequence.id,
                    exposure_id=exposure.id,
                    config_id=sequence.config_snapshot_id,
                )
                l1_hash = _science_product_hash(run, "L1-v1", [raw.sha256])
                l1_product = await _register_product(
                    session,
                    run=run,
                    sequence=sequence,
                    exposure_id=exposure.id,
                    level=ProductLevel.L1,
                    mode=mode,
                    path=l1_path,
                    product_hash=l1_hash,
                    schema_version="L1-v1",
                    metadata=l1_frame.provenance,
                    inputs=[(raw.id, "RAW_FILE", raw.sha256)],
                )
                spectra = calibrate_simulated_thar(extract_simulation_channels(l1_frame, mode))
                l2_path = root / "L2" / f"{exposure.id}.fits"
                write_l2(
                    spectra,
                    l2_path,
                    mode=mode,
                    sequence_id=sequence.id,
                    exposure_id=exposure.id,
                    config_id=sequence.config_snapshot_id,
                )
                l2_hash = _science_product_hash(
                    run,
                    "L2-v1",
                    [l1_product.product_hash],
                )
                l2_product = await _register_product(
                    session,
                    run=run,
                    sequence=sequence,
                    exposure_id=exposure.id,
                    level=ProductLevel.L2,
                    mode=mode,
                    path=l2_path,
                    product_hash=l2_hash,
                    schema_version="L2-v1",
                    metadata=spectra.provenance,
                    inputs=[(l1_product.id, "PRODUCT", l1_product.sha256)],
                )
                l2_outputs.append((exposure, raw, spectra, l2_product))
                run.progress = 0.1 + 0.65 * index / len(rows)
                run.updated_at = utcnow()
                await session.commit()

            if mode.is_polarimetric:
                null_sigma_threshold = float(qc_configuration()["null_sigma_threshold"])
                for group_start in range(0, len(l2_outputs), 4):
                    group_rows = l2_outputs[group_start : group_start + 4]
                    if len(group_rows) != 4:
                        raise ValueError("polarimetric group is incomplete")
                    beams = [
                        BeamSpectrum(
                            wavelength=item[2].channels["O_BEAM"].wavelength,
                            o_flux=item[2].channels["O_BEAM"].flux,
                            e_flux=item[2].channels["E_BEAM"].flux,
                            o_variance=item[2].channels["O_BEAM"].variance,
                            e_variance=item[2].channels["E_BEAM"].variance,
                            dq=np.bitwise_or(
                                item[2].channels["O_BEAM"].dq,
                                item[2].channels["E_BEAM"].dq,
                            ),
                            sub_index=item[0].sub_index,
                            exposure_id=item[0].id,
                            flux_unit=item[2].channels["O_BEAM"].unit,
                            wavelength_unit=item[2].channels["O_BEAM"].wavelength_unit,
                            config_version=item[2].config_version,
                            provenance=item[2].provenance,
                        )
                        for item in group_rows
                    ]
                    polar = demodulate_group(
                        beams,
                        null_sigma_threshold=null_sigma_threshold,
                    )
                    group_id = group_rows[0][0].group_id or "NA"
                    path = root / "L3" / f"{group_id}-{mode.value}.fits"
                    exposure_metadata = [
                        {
                            "exposure_id": item[0].id,
                            "sub_index": item[0].sub_index,
                            "fr1_cmd": item[0].fr1_commanded,
                            "fr1_meas": item[0].fr1_measured,
                            "fr3_cmd": item[0].fr3_commanded,
                            "fr3_meas": item[0].fr3_measured,
                        }
                        for item in group_rows
                    ]
                    write_polar_l3(
                        polar,
                        path,
                        mode=mode,
                        sequence_id=sequence.id,
                        group_id=group_id,
                        config_id=sequence.config_snapshot_id,
                        exposure_rows=exposure_metadata,
                    )
                    product_hash = _science_product_hash(
                        run,
                        "POL-L3-v1",
                        [item[3].product_hash for item in group_rows],
                    )
                    product = await _register_product(
                        session,
                        run=run,
                        sequence=sequence,
                        exposure_id=None,
                        level=ProductLevel.L3,
                        mode=mode,
                        path=path,
                        product_hash=product_hash,
                        schema_version="L3-v1",
                        metadata={"group_id": group_id, **polar.qc},
                        inputs=[(item[3].id, "PRODUCT", item[3].sha256) for item in group_rows],
                    )
                    for metric in (
                        "null1_rms",
                        "null2_rms",
                        "null1_max_sigma",
                        "null2_max_sigma",
                    ):
                        value = float(polar.qc[metric])
                        threshold = null_sigma_threshold if "max_sigma" in metric else None
                        session.add(
                            QCResult(
                                product_id=product.id,
                                metric=metric,
                                value=value,
                                threshold=threshold,
                                passed=threshold is None or value <= threshold,
                                reason_code=(
                                    "SIMULATION_METRIC"
                                    if threshold is None or value <= threshold
                                    else f"{metric.upper()}_EXCESS"
                                ),
                            )
                        )
            else:
                for exposure, _, spectra, l2_product in l2_outputs:
                    target = spectra.channels["TARGET"]
                    sky = spectra.channels["SKY"]
                    alpha = np.ones_like(target.flux)
                    product_data = subtract_sky(
                        target.wavelength,
                        target.flux,
                        sky.flux,
                        alpha,
                        target.variance,
                        sky.variance,
                        np.full_like(alpha, 1e-6),
                        np.bitwise_or(target.dq, sky.dq),
                        flux_unit=target.unit,
                        wavelength_unit=target.wavelength_unit,
                        config_version=spectra.config_version,
                        provenance={
                            "target_channel": target.role,
                            "sky_channel": sky.role,
                        },
                    )
                    path = root / "L3" / f"{exposure.id}-NONPOL.fits"
                    write_nonpolar_l3(
                        product_data,
                        path,
                        sequence_id=sequence.id,
                        exposure_id=exposure.id,
                        config_id=sequence.config_snapshot_id,
                    )
                    product_hash = _science_product_hash(
                        run,
                        "NONPOL-L3-v1",
                        [l2_product.product_hash],
                    )
                    product = await _register_product(
                        session,
                        run=run,
                        sequence=sequence,
                        exposure_id=exposure.id,
                        level=ProductLevel.L3,
                        mode=mode,
                        path=path,
                        product_hash=product_hash,
                        schema_version="L3-v1",
                        metadata={"background_subtracted": product_data.background_subtracted},
                        inputs=[(l2_product.id, "PRODUCT", l2_product.sha256)],
                    )
                    session.add(
                        QCResult(
                            product_id=product.id,
                            metric="sky_valid",
                            value=1.0 if product_data.background_subtracted else 0.0,
                            threshold=1.0,
                            passed=product_data.background_subtracted,
                            reason_code=(
                                "SIMULATION_SKY_VALID"
                                if product_data.background_subtracted
                                else "SKY_INVALID"
                            ),
                        )
                    )

            run.status = ProcessingStatus.SUCCEEDED
            run.progress = 1.0
            run.updated_at = utcnow()
            task.status = ProcessingStatus.SUCCEEDED
            task.metrics_json = {"product_count": len(l2_outputs), "mode": mode.value}
            await emit_event(
                session,
                EventType.PROCESSING_RUN_STATE_CHANGED,
                correlation_id=sequence.id,
                sequence_id=sequence.id,
                payload={"processing_run_id": run.id, "status": ProcessingStatus.SUCCEEDED},
            )
    except Exception as exc:
        logger.exception("processing_run_failed", processing_run_id=run_id, error=str(exc))
        async with session_scope() as session:
            run = await session.get(ProcessingRun, run_id)
            if run is not None:
                run.status = ProcessingStatus.FAILED
                run.error_code = getattr(exc, "code", "PROCESSING_FAILURE")
                run.error_message = str(exc)
                run.updated_at = utcnow()
                task = await session.scalar(
                    select(TaskRun).where(
                        TaskRun.processing_run_id == run.id,
                        TaskRun.task_name == "l0-to-l3",
                    )
                )
                if task is not None:
                    task.status = ProcessingStatus.FAILED
                    task.error_json = {
                        "code": run.error_code,
                        "message": run.error_message,
                    }
                await emit_event(
                    session,
                    EventType.PROCESSING_RUN_STATE_CHANGED,
                    correlation_id=run.sequence_id,
                    sequence_id=run.sequence_id,
                    payload={
                        "processing_run_id": run.id,
                        "status": ProcessingStatus.FAILED,
                        "error": str(exc),
                    },
                )
        raise
