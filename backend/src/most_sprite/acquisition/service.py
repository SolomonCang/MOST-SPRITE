from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import structlog
from astropy.io import fits
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.acquisition.fits_contract import validate_l0, write_l0_atomic
from most_sprite.config import get_settings
from most_sprite.db.models import Command, Exposure, Product, RawFile, Sequence
from most_sprite.domain.enums import (
    CommandStatus,
    DataMode,
    EventType,
    ExposureStatus,
    ProductLevel,
    QCFlag,
)
from most_sprite.errors import SpriteError
from most_sprite.events import emit_event

logger = structlog.get_logger(__name__)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class AcquisitionService:
    async def commit_l0(
        self,
        session: AsyncSession,
        *,
        exposure: Exposure,
        mode: DataMode,
        config_snapshot_id: str,
        image: np.ndarray,
        telemetry: dict,
        exposure_time: float,
        started_at: datetime,
        ended_at: datetime,
    ) -> RawFile:
        existing = await session.scalar(select(RawFile).where(RawFile.exposure_id == exposure.id))
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        night_id = now.strftime("%Y%m%d-sim")
        final_path = (
            get_settings().data_root
            / "raw"
            / now.strftime("%Y")
            / now.strftime("%m")
            / now.strftime("%d")
            / night_id
            / f"{exposure.id}.fits"
        )
        raw_file_id = str(uuid4())
        command_id = exposure.command_id or "NA"
        if final_path.exists():
            validate_l0(final_path)
            with fits.open(final_path, checksum=True, memmap=False) as existing_file:
                raw_file_id = str(existing_file[0].header["RAWFILE"])
                command_id = str(existing_file[0].header["CMDID"])
        checksum, datasum = write_l0_atomic(
            final_path,
            image,
            raw_file_id=raw_file_id,
            sequence_id=exposure.sequence_id,
            group_id=exposure.group_id,
            exposure_id=exposure.id,
            command_id=command_id,
            config_snapshot_id=config_snapshot_id,
            mode=mode,
            sub_index=exposure.sub_index,
            exposure_time=exposure_time,
            started_at=started_at,
            ended_at=ended_at,
            fr1_commanded=exposure.fr1_commanded,
            fr1_measured=exposure.fr1_measured,
            fr3_commanded=exposure.fr3_commanded,
            fr3_measured=exposure.fr3_measured,
            telemetry=telemetry,
        )
        digest = sha256_file(final_path)
        if command_id != "NA" and await session.get(Command, command_id) is None:
            session.add(
                Command(
                    id=command_id,
                    idempotency_key=f"recovered-l0:{command_id}",
                    sequence_id=exposure.sequence_id,
                    device_id="detector",
                    command_type="RECOVERED_EXPOSE",
                    parameters_json={"recovered_from": str(final_path.resolve())},
                    status=CommandStatus.SUCCEEDED,
                    completed_at=ended_at,
                )
            )
            exposure.command_id = command_id
        raw = RawFile(
            id=raw_file_id,
            exposure_id=exposure.id,
            uri=str(final_path.resolve()),
            size=final_path.stat().st_size,
            sha256=digest,
            fits_checksum=checksum,
            fits_datasum=datasum,
        )
        session.add(raw)
        exposure.raw_file_id = raw.id
        exposure.status = ExposureStatus.COMMITTED
        exposure.committed_at = ended_at
        session.add(
            Product(
                sequence_id=exposure.sequence_id,
                exposure_id=exposure.id,
                level=ProductLevel.L0,
                mode=mode,
                uri=str(final_path.resolve()),
                size=final_path.stat().st_size,
                sha256=digest,
                product_hash=digest,
                schema_version="L0-v1",
                qc_flag=QCFlag.SIMULATION_ONLY,
                metadata_json={"raw_file_id": raw.id, "immutable": True},
            )
        )
        await emit_event(
            session,
            EventType.RAW_FILE_COMMITTED,
            correlation_id=exposure.sequence_id,
            causation_id=exposure.command_id,
            sequence_id=exposure.sequence_id,
            group_id=exposure.group_id,
            exposure_id=exposure.id,
            config_snapshot_id=config_snapshot_id,
            payload={"raw_file_id": raw.id, "uri": raw.uri, "sha256": digest},
        )
        await session.flush()
        return raw


async def recover_unregistered_l0(session: AsyncSession) -> int:
    recovered = 0
    for path in get_settings().data_root.glob("raw/**/*.fits"):
        try:
            validate_l0(path)
        except (SpriteError, OSError, ValueError) as exc:
            logger.warning("invalid_l0_skipped_during_recovery", path=str(path), error=str(exc))
            continue
        with fits.open(path, checksum=True, memmap=False) as hdul:
            header = hdul[0].header
            exposure_id = str(header["EXPID"])
            raw_file_id = str(header["RAWFILE"])
            existing = await session.get(RawFile, raw_file_id)
            if existing is not None:
                continue
            exposure = await session.get(Exposure, exposure_id)
            if exposure is None:
                continue
            command_id = str(header["CMDID"])
            if command_id != "NA" and await session.get(Command, command_id) is None:
                session.add(
                    Command(
                        id=command_id,
                        idempotency_key=f"recovered-l0:{command_id}",
                        sequence_id=exposure.sequence_id,
                        device_id="detector",
                        command_type="RECOVERED_EXPOSE",
                        parameters_json={"recovered_from": str(path.resolve())},
                        status=CommandStatus.SUCCEEDED,
                        completed_at=datetime.fromisoformat(str(header["DATE-END"])),
                    )
                )
                exposure.command_id = command_id
            digest = sha256_file(path)
            raw = RawFile(
                id=raw_file_id,
                exposure_id=exposure_id,
                uri=str(path.resolve()),
                size=path.stat().st_size,
                sha256=digest,
                fits_checksum=str(header["CHECKSUM"]),
                fits_datasum=str(header["DATASUM"]),
            )
            session.add(raw)
            was_committed = exposure.status == ExposureStatus.COMMITTED
            exposure.raw_file_id = raw_file_id
            exposure.status = ExposureStatus.COMMITTED
            exposure.committed_at = datetime.fromisoformat(str(header["DATE-END"]))
            product = await session.scalar(select(Product).where(Product.product_hash == digest))
            if product is None:
                session.add(
                    Product(
                        sequence_id=exposure.sequence_id,
                        exposure_id=exposure.id,
                        level=ProductLevel.L0,
                        mode=str(header["DATAMODE"]),
                        uri=str(path.resolve()),
                        size=path.stat().st_size,
                        sha256=digest,
                        product_hash=digest,
                        schema_version=str(header["SCHEMVER"]),
                        qc_flag=QCFlag.SIMULATION_ONLY,
                        metadata_json={
                            "raw_file_id": raw.id,
                            "immutable": True,
                            "recovered": True,
                        },
                    )
                )
            sequence = await session.get(Sequence, exposure.sequence_id)
            if sequence is not None and not was_committed:
                sequence.completed_exposures = min(
                    sequence.expected_exposures, sequence.completed_exposures + 1
                )
            await emit_event(
                session,
                EventType.RAW_FILE_COMMITTED,
                correlation_id=exposure.sequence_id,
                causation_id=exposure.command_id,
                sequence_id=exposure.sequence_id,
                group_id=exposure.group_id,
                exposure_id=exposure.id,
                config_snapshot_id=str(header["CONFIGID"]),
                payload={"raw_file_id": raw_file_id, "uri": raw.uri, "recovered": True},
            )
            recovered += 1
    return recovered
