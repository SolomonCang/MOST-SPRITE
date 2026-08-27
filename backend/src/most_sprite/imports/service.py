from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from astropy.time import Time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.acquisition.fits_contract import write_l0_atomic
from most_sprite.config import get_settings
from most_sprite.configuration import content_hash
from most_sprite.db.models import (
    ConfigSnapshot,
    Exposure,
    ImportBatch,
    ImportedArtifact,
    ImportInspection,
    ModulationGroup,
    Product,
    ProductInput,
    RawFile,
    Sequence,
)
from most_sprite.domain.enums import (
    ConfigurationStatus,
    DataMode,
    EventType,
    ExposureStatus,
    ImportStatus,
    ProductLevel,
    PublicationStatus,
    QCFlag,
    SequenceStatus,
)
from most_sprite.errors import SpriteError
from most_sprite.events import emit_event
from most_sprite.pipeline.instruments import instrument_adapter
from most_sprite.pipeline.instruments.espadons import sha256_file


def _resolve_source(root_id: str, relative_path: str) -> tuple[Path, Path]:
    settings = get_settings()
    root = settings.import_roots.get(root_id)
    if root is None:
        raise SpriteError(
            "IMPORT_ROOT_NOT_FOUND",
            "the requested import root is not configured",
            status_code=404,
            details={"root_id": root_id},
        )
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SpriteError(
            "IMPORT_PATH_FORBIDDEN",
            "import paths must be relative and cannot traverse parents",
            status_code=422,
        )
    try:
        root = root.resolve(strict=True)
        source = (root / relative).resolve(strict=True)
    except OSError as exc:
        raise SpriteError(
            "IMPORT_PATH_NOT_FOUND",
            "the requested import directory does not exist",
            status_code=404,
        ) from exc
    if source != root and root not in source.parents:
        raise SpriteError(
            "IMPORT_PATH_FORBIDDEN",
            "the resolved source escapes its configured import root",
            status_code=422,
        )
    if not source.is_dir():
        raise SpriteError("IMPORT_PATH_NOT_DIRECTORY", "the import source must be a directory")
    return root, source


def _candidate_files(root: Path, source: Path) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    for candidate in sorted(source.rglob("*")):
        if candidate.is_symlink():
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise SpriteError(
                    "IMPORT_PATH_FORBIDDEN",
                    f"broken symbolic link in import directory: {candidate.name}",
                ) from exc
            if resolved != root and root not in resolved.parents:
                raise SpriteError(
                    "IMPORT_PATH_FORBIDDEN",
                    "an import symlink escapes the configured root",
                    status_code=422,
                    details={"path": str(candidate.relative_to(root))},
                )
        resolved = candidate.resolve()
        if not resolved.is_file():
            continue
        if root not in resolved.parents:
            raise SpriteError("IMPORT_PATH_FORBIDDEN", "an import file escapes its root")
        lower = candidate.name.lower()
        if lower.endswith((".fits", ".fit", ".fits.fz", ".fit.fz")):
            result.append((resolved, candidate.relative_to(root).as_posix()))
    if not result:
        raise SpriteError(
            "IMPORT_EMPTY",
            "the selected directory contains no FITS artifacts",
            status_code=422,
        )
    return result


def _manifest_digest(records: list[dict[str, Any]]) -> str:
    stable = [
        {
            "relative_path": item["relative_path"],
            "size": item["size"],
            "sha256": item["sha256"],
            "role": item["role"],
            "detector": item["detector"],
            "stokes": item["stokes"],
            "sub_index": item["sub_index"],
        }
        for item in records
    ]
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scan(root: Path, source: Path, instrument: str) -> dict[str, Any]:
    adapter = instrument_adapter(instrument)
    descriptors = [
        adapter.inspect(path, relative_path=relative)
        for path, relative in _candidate_files(root, source)
    ]
    groups = adapter.group_science(descriptors)
    inventory = [item.manifest_record() for item in descriptors]
    counts: dict[str, int] = {}
    for item in descriptors:
        counts[item.role] = counts.get(item.role, 0) + 1
    warnings: list[dict[str, Any]] = []
    requirements = {"BIAS": 3, "FLAT": 10, "THAR": 1, "ALIGNMENT": 1}
    for role, minimum in requirements.items():
        actual = counts.get(role, 0)
        if actual < minimum:
            warnings.append(
                {
                    "code": f"{role}_COUNT_LOW",
                    "message": f"{role}: found {actual}; calibration requires at least {minimum}",
                    "blocking_calibration": True,
                    "actual": actual,
                    "minimum": minimum,
                }
            )
    flat_count = counts.get("FLAT", 0)
    if 10 <= flat_count < 20:
        warnings.append(
            {
                "code": "FLAT_COUNT_BELOW_RECOMMENDED",
                "message": "10 flats are accepted by QC, while CFHT recommends 20–40",
                "blocking_calibration": False,
                "actual": flat_count,
                "recommended": 20,
            }
        )
    unknown = [item.relative_path for item in descriptors if item.role == "UNKNOWN"]
    if unknown:
        warnings.append(
            {
                "code": "UNCLASSIFIED_ARTIFACTS",
                "message": "unclassified FITS files are retained but never used for science",
                "blocking_calibration": False,
                "paths": unknown,
            }
        )
    return {
        "inventory": inventory,
        "groups": groups,
        "calibration_summary": {"counts": counts, "requirements": requirements},
        "warnings": warnings,
        "manifest_sha256": _manifest_digest(inventory),
    }


async def inspect_import_directory(
    session: AsyncSession,
    *,
    idempotency_key: str,
    root_id: str,
    relative_path: str,
    instrument: str,
    created_by: str,
) -> ImportInspection:
    existing = await session.scalar(
        select(ImportInspection).where(
            ImportInspection.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.root_id != root_id
            or existing.relative_path != relative_path
            or existing.instrument != instrument
        ):
            raise SpriteError(
                "IDEMPOTENCY_CONFLICT",
                "this Idempotency-Key was already used for a different inspection",
                status_code=409,
            )
        return existing
    root, source = _resolve_source(root_id, relative_path)
    inspection = ImportInspection(
        idempotency_key=idempotency_key,
        root_id=root_id,
        relative_path=relative_path,
        instrument=instrument,
        status=ImportStatus.RUNNING,
        created_by=created_by,
    )
    session.add(inspection)
    await session.flush()
    try:
        result = await asyncio.to_thread(_scan, root, source, instrument)
    except Exception as exc:
        inspection.status = ImportStatus.FAILED
        inspection.error_code = getattr(exc, "code", "IMPORT_INSPECTION_FAILED")
        inspection.error_message = str(exc)
        inspection.updated_at = datetime.now(UTC)
        return inspection
    inspection.status = ImportStatus.SUCCEEDED
    inspection.manifest_sha256 = result["manifest_sha256"]
    inspection.inventory_json = result["inventory"]
    inspection.groups_json = result["groups"]
    inspection.calibration_summary_json = result["calibration_summary"]
    inspection.warnings_json = result["warnings"]
    inspection.updated_at = datetime.now(UTC)
    await emit_event(
        session,
        EventType.IMPORT_INSPECTION_COMPLETED,
        correlation_id=inspection.id,
        payload={
            "inspection_id": inspection.id,
            "status": inspection.status,
            "manifest_sha256": inspection.manifest_sha256,
        },
    )
    return inspection


def _copy_verified(
    source: Path, destination: Path, expected_sha256: str, expected_size: int
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if (
            destination.stat().st_size == expected_size
            and sha256_file(destination) == expected_sha256
        ):
            return
        raise SpriteError(
            "IMPORT_IMMUTABLE_CONFLICT",
            "managed import path already contains different bytes",
            status_code=409,
        )
    part = destination.with_suffix(destination.suffix + ".part")
    if part.exists():
        part.unlink()
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, part.open("xb") as writer:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            writer.write(block)
            digest.update(block)
            size += len(block)
        writer.flush()
        os.fsync(writer.fileno())
    if size != expected_size or digest.hexdigest() != expected_sha256:
        part.unlink(missing_ok=True)
        raise SpriteError(
            "SOURCE_CHANGED",
            "an import source changed after inspection",
            status_code=409,
            details={"source": source.name},
        )
    os.replace(part, destination)
    dir_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


async def _espadons_config(session: AsyncSession) -> ConfigSnapshot:
    payload = {
        "schema_version": 1,
        "version": "espadons-olapa-v1",
        "status": "UNVERIFIED",
        "instrument": "ESPADONS",
        "detector": {
            "profile": "OLAPA",
            "canonical_axes": ["cross_dispersion", "dispersion"],
            "data_section_policy": "FITS_HEADER",
            "overscan_policy": "FITS_HEADER_PER_AMPLIFIER",
        },
        "polarimetry": {
            "beam_roles": ["O_BEAM", "E_BEAM"],
            "sub_exposures": 4,
            "continuum_polarization": "UNSUPPORTED",
        },
    }
    digest = content_hash(payload)
    existing = await session.scalar(
        select(ConfigSnapshot).where(ConfigSnapshot.content_hash == digest)
    )
    if existing is not None:
        return existing
    snapshot = ConfigSnapshot(
        version=payload["version"],
        status=ConfigurationStatus.UNVERIFIED,
        content_hash=digest,
        payload_json=payload,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


def _observed_at(record: dict[str, Any]) -> datetime:
    header = record.get("header", {})
    mjd = header.get("MJD-OBS") or header.get("MJDATE")
    if mjd is not None:
        return Time(float(mjd), format="mjd").to_datetime(timezone=UTC)
    value = record.get("observed_at")
    if value:
        try:
            date, clock = str(value).split("T", 1)
            parts = clock.split(":")
            if len(parts[0]) == 1:
                clock = f"0{clock}"
            parsed = datetime.fromisoformat(f"{date}T{clock}")
            return parsed.replace(tzinfo=parsed.tzinfo or UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


async def commit_import(
    session: AsyncSession,
    *,
    inspection_id: str,
    manifest_sha256: str,
    idempotency_key: str,
    created_by: str,
) -> ImportBatch:
    existing = await session.scalar(
        select(ImportBatch).where(ImportBatch.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.inspection_id != inspection_id
            or existing.manifest_sha256 != manifest_sha256
        ):
            raise SpriteError(
                "IDEMPOTENCY_CONFLICT",
                "this Idempotency-Key was already used for a different import",
                status_code=409,
            )
        return existing
    existing_manifest = await session.scalar(
        select(ImportBatch).where(
            ImportBatch.manifest_sha256 == manifest_sha256,
            ImportBatch.status == ImportStatus.SUCCEEDED,
        )
    )
    if existing_manifest is not None:
        return existing_manifest
    inspection = await session.get(ImportInspection, inspection_id)
    if inspection is None:
        raise SpriteError(
            "IMPORT_INSPECTION_NOT_FOUND", "inspection does not exist", status_code=404
        )
    if inspection.status != ImportStatus.SUCCEEDED:
        raise SpriteError(
            "IMPORT_INSPECTION_NOT_READY",
            "only a successful inspection can be committed",
            status_code=409,
        )
    if inspection.manifest_sha256 != manifest_sha256:
        raise SpriteError(
            "SOURCE_CHANGED",
            "the submitted manifest does not match the inspection",
            status_code=409,
        )
    root, _ = _resolve_source(inspection.root_id, inspection.relative_path)
    batch = ImportBatch(
        inspection_id=inspection.id,
        idempotency_key=idempotency_key,
        manifest_sha256=manifest_sha256,
        status=ImportStatus.RUNNING,
        created_by=created_by,
    )
    session.add(batch)
    await session.flush()
    savepoint = await session.begin_nested()
    managed_root = get_settings().data_root / "imports" / batch.id / "source"
    copied: dict[str, Path] = {}
    try:
        for record in inspection.inventory_json:
            source = (root / record["relative_path"]).resolve(strict=True)
            if root not in source.parents:
                raise SpriteError("IMPORT_PATH_FORBIDDEN", "source escaped its configured root")
            destination = managed_root / record["sha256"][:2] / Path(record["relative_path"]).name
            await asyncio.to_thread(
                _copy_verified,
                source,
                destination,
                record["sha256"],
                int(record["size"]),
            )
            copied[record["relative_path"]] = destination
        # Recompute the immutable manifest from managed bytes before any DB
        # artifact or science sequence becomes visible.
        managed_records = []
        for record in inspection.inventory_json:
            copied_path = copied[record["relative_path"]]
            managed_record = dict(record)
            managed_record["size"] = copied_path.stat().st_size
            managed_record["sha256"] = await asyncio.to_thread(sha256_file, copied_path)
            managed_records.append(managed_record)
        if _manifest_digest(managed_records) != manifest_sha256:
            raise SpriteError("SOURCE_CHANGED", "managed import manifest differs from inspection")

        artifact_models: dict[str, ImportedArtifact] = {}
        for record in managed_records:
            artifact = ImportedArtifact(
                import_batch_id=batch.id,
                relative_path=record["relative_path"],
                managed_uri=str(copied[record["relative_path"]].resolve()),
                size=int(record["size"]),
                sha256=record["sha256"],
                artifact_role=record["role"],
                instrument=record["instrument"],
                detector=record["detector"],
                header_json=record.get("header", {}),
            )
            session.add(artifact)
            artifact_models[record["relative_path"]] = artifact
        await session.flush()

        config = await _espadons_config(session)
        adapter = instrument_adapter(inspection.instrument)
        sequence_ids: list[str] = []
        records_by_path = {item["relative_path"]: item for item in managed_records}
        for group in inspection.groups_json:
            sequence = Sequence(
                idempotency_key=f"import:{manifest_sha256}:{group['group_key']}",
                target_name=group["target_name"],
                mode=group["mode"],
                exposure_time=float(group["exposure_time"]),
                repeats=1,
                expected_exposures=4,
                completed_exposures=4,
                status=SequenceStatus.SUCCEEDED,
                config_snapshot_id=config.id,
                created_by=created_by,
            )
            session.add(sequence)
            await session.flush()
            modulation_group = ModulationGroup(
                sequence_id=sequence.id,
                group_index=int(group["sequence_number"]),
                stokes=group["stokes"],
                status="COMMITTED",
            )
            session.add(modulation_group)
            await session.flush()
            sequence_ids.append(sequence.id)
            for sub_index, relative_path in enumerate(group["artifacts"], start=1):
                record = records_by_path[relative_path]
                started = _observed_at(record)
                ended = started + timedelta(seconds=float(record["exposure_time"]))
                exposure = Exposure(
                    sequence_id=sequence.id,
                    group_id=modulation_group.id,
                    sub_index=sub_index,
                    status=ExposureStatus.COMMITTED,
                    started_at=started,
                    committed_at=ended,
                )
                session.add(exposure)
                await session.flush()
                artifact = artifact_models[relative_path]
                artifact.sequence_id = sequence.id
                artifact.exposure_id = exposure.id
                raw = RawFile(
                    exposure_id=exposure.id,
                    uri=artifact.managed_uri,
                    size=artifact.size,
                    sha256=artifact.sha256,
                    fits_checksum="SOURCE_SHA256",
                    fits_datasum="SOURCE_SHA256",
                    status="COMMITTED",
                    instrument="ESPADONS",
                    detector_profile="OLAPA",
                    source_format=record["source_format"],
                    imported_artifact_id=artifact.id,
                )
                session.add(raw)
                await session.flush()
                exposure.raw_file_id = raw.id

                image, l0_provenance, profile = await asyncio.to_thread(
                    adapter.canonical_image, Path(artifact.managed_uri)
                )
                l0_path = (
                    get_settings().data_root
                    / "products"
                    / sequence.id
                    / "import"
                    / "L0"
                    / f"{exposure.id}.fits"
                )
                fits_checksum, fits_datasum = await asyncio.to_thread(
                    write_l0_atomic,
                    l0_path,
                    image,
                    raw_file_id=raw.id,
                    sequence_id=sequence.id,
                    group_id=modulation_group.id,
                    exposure_id=exposure.id,
                    command_id=batch.id,
                    config_snapshot_id=config.id,
                    mode=DataMode(record["mode"]),
                    sub_index=sub_index,
                    exposure_time=float(record["exposure_time"]),
                    started_at=started,
                    ended_at=ended,
                    fr1_commanded=None,
                    fr1_measured=None,
                    fr3_commanded=None,
                    fr3_measured=None,
                    telemetry={"source": relative_path, "import_batch_id": batch.id},
                    simulation=False,
                    instrument="ESPADONS",
                    detector="OLAPA",
                    calibration_version="UNAPPLIED",
                    modulation_version="espadons-ratio-v1",
                    qc_flag="PASS",
                    source_header=record.get("header", {}),
                    provenance=l0_provenance,
                    axis_map=profile.axis_transform,
                )
                raw.fits_checksum = fits_checksum
                raw.fits_datasum = fits_datasum
                product_hash = hashlib.sha256(
                    f"ESPADONS-L0-v1:{raw.sha256}:{config.content_hash}".encode()
                ).hexdigest()
                product = Product(
                    processing_run_id=None,
                    sequence_id=sequence.id,
                    exposure_id=exposure.id,
                    level=ProductLevel.L0,
                    mode=record["mode"],
                    uri=str(l0_path.resolve()),
                    size=l0_path.stat().st_size,
                    sha256=await asyncio.to_thread(sha256_file, l0_path),
                    product_hash=product_hash,
                    schema_version="L0-v1",
                    qc_flag=QCFlag.PASS,
                    metadata_json={
                        **l0_provenance,
                        "simulation_only": False,
                        "publishable": False,
                        "source_sha256": raw.sha256,
                    },
                    instrument="ESPADONS",
                    detector_profile="OLAPA",
                    import_batch_id=batch.id,
                    publication_status=PublicationStatus.DRAFT,
                )
                session.add(product)
                await session.flush()
                session.add(
                    ProductInput(
                        product_id=product.id,
                        input_id=raw.id,
                        input_kind="RAW_FILE",
                        input_checksum=raw.sha256,
                    )
                )
        batch.sequence_ids_json = sequence_ids
        batch.status = ImportStatus.SUCCEEDED
        batch.updated_at = datetime.now(UTC)
        await emit_event(
            session,
            EventType.IMPORT_COMPLETED,
            correlation_id=batch.id,
            payload={
                "import_batch_id": batch.id,
                "status": batch.status,
                "sequence_ids": sequence_ids,
            },
        )
        await savepoint.commit()
    except Exception as exc:
        if savepoint.is_active:
            await savepoint.rollback()
        batch.status = ImportStatus.FAILED
        batch.error_code = getattr(exc, "code", "IMPORT_FAILED")
        batch.error_message = str(exc)
        batch.updated_at = datetime.now(UTC)
        # Uncommitted product files are recoverable orphans and are ignored by
        # readers; source copies remain content-addressed for a safe retry.
    return batch
