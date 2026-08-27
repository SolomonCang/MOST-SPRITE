from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from most_sprite.config import get_settings
from most_sprite.configuration import qc_configuration
from most_sprite.domain.enums import DataMode
from most_sprite.errors import SpriteError

REQUIRED_L0_KEYS = {
    "SCHEMVER",
    "PRODLEV",
    "DATAMODE",
    "STOKES",
    "NORMSTAT",
    "WAVETYPE",
    "SPECSYS",
    "SEQID",
    "GROUPID",
    "EXPID",
    "RAWFILE",
    "CMDID",
    "CONFIGID",
    "SUBIDX",
    "PIPENAME",
    "PIPEVER",
    "SWCOMMIT",
    "CALVER",
    "MODVER",
    "MUELLVER",
    "TIMESYS",
    "DATE-OBS",
    "DATE-END",
    "EXPTIME",
    "FR1CMD",
    "FR1MEAS",
    "FR3CMD",
    "FR3MEAS",
    "CHANMAP",
    "QCFLAG",
    "CHECKSUM",
    "DATASUM",
}


def _text_table(name: str, rows: list[tuple[str, str, str, str]]) -> fits.BinTableHDU:
    columns = [
        fits.Column(name="NAME", format="32A", array=[row[0] for row in rows]),
        fits.Column(name="VALUE", format="128A", array=[row[1] for row in rows]),
        fits.Column(name="UNIT", format="24A", array=[row[2] for row in rows]),
        fits.Column(name="QUALITY", format="16A", array=[row[3] for row in rows]),
    ]
    return fits.BinTableHDU.from_columns(columns, name=name)


def write_l0_atomic(
    final_path: Path,
    image: np.ndarray,
    *,
    raw_file_id: str,
    sequence_id: str,
    group_id: str | None,
    exposure_id: str,
    command_id: str,
    config_snapshot_id: str,
    mode: DataMode,
    sub_index: int,
    exposure_time: float,
    started_at: datetime,
    ended_at: datetime,
    fr1_commanded: float | None,
    fr1_measured: float | None,
    fr3_commanded: float | None,
    fr3_measured: float | None,
    telemetry: dict[str, Any],
    simulation: bool = True,
    instrument: str = "MOST",
    detector: str = "SIMULATED",
    calibration_version: str = "SIMULATION-v1",
    modulation_version: str = "most-v1",
    qc_flag: str | None = None,
    source_header: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    axis_map: str = "DETECTOR_Y/DETECTOR_X",
) -> tuple[str, str]:
    if telemetry.get("storage_fault"):
        raise SpriteError(
            "STORAGE_FULL",
            "simulated storage hard limit prevented L0 commit",
            status_code=507,
            retryable=True,
        )
    settings = get_settings()
    final_path.parent.mkdir(parents=True, exist_ok=True)
    minimum_free_bytes = int(qc_configuration()["minimum_free_bytes"])
    available_bytes = shutil.disk_usage(final_path.parent).free
    if not final_path.exists() and available_bytes < minimum_free_bytes:
        raise SpriteError(
            "STORAGE_LOW_WATERMARK",
            "storage is below the frozen safe free-space threshold",
            status_code=507,
            retryable=True,
            details={
                "available_bytes": available_bytes,
                "minimum_free_bytes": minimum_free_bytes,
            },
        )
    part_path = final_path.with_suffix(final_path.suffix + ".part")
    if final_path.exists():
        validate_l0(final_path)
        with fits.open(final_path, checksum=True) as existing:
            expected = {
                "RAWFILE": raw_file_id,
                "SEQID": sequence_id,
                "EXPID": exposure_id,
                "CMDID": command_id,
                "CONFIGID": config_snapshot_id,
                "DATAMODE": mode.value,
                "SUBIDX": sub_index,
            }
            conflicts = {
                key: {"expected": value, "actual": existing[0].header.get(key)}
                for key, value in expected.items()
                if existing[0].header.get(key) != value
            }
            if existing[0].data.shape != image.shape:
                conflicts["SHAPE"] = {
                    "expected": list(image.shape),
                    "actual": list(existing[0].data.shape),
                }
            if conflicts:
                raise SpriteError(
                    "L0_IMMUTABLE_CONFLICT",
                    "an existing L0 cannot be replaced by different content",
                    status_code=409,
                    details={"conflicts": conflicts},
                )
            return str(existing[0].header["CHECKSUM"]), str(existing[0].header["DATASUM"])
    if part_path.exists():
        part_path.unlink()

    primary = fits.PrimaryHDU(np.asarray(image, dtype=np.uint16))
    header = primary.header
    header["SCHEMVER"] = "L0-v1"
    header["PRODLEV"] = "L0"
    header["DATAMODE"] = mode.value
    header["STOKES"] = mode.value[-1] if mode.is_polarimetric else "NA"
    header["NORMSTAT"] = "UNNORMALIZED"
    header["WAVETYPE"] = "UNVERIFIED"
    header["SPECSYS"] = "TOPOCENT"
    header["SEQID"] = sequence_id
    header["GROUPID"] = group_id or "NA"
    header["EXPID"] = exposure_id
    header["RAWFILE"] = raw_file_id
    header["CMDID"] = command_id
    header["CONFIGID"] = config_snapshot_id
    header["SUBIDX"] = sub_index
    header["PIPENAME"] = "MOST-SPRITE"
    header["PIPEVER"] = settings.software_version
    header["SWCOMMIT"] = settings.software_commit
    header["CALVER"] = calibration_version
    header["MODVER"] = modulation_version
    header["MUELLVER"] = "UNAPPLIED"
    header["TIMESYS"] = "UTC"
    header["DATE-OBS"] = started_at.astimezone(UTC).isoformat()
    header["DATE-END"] = ended_at.astimezone(UTC).isoformat()
    header["EXPTIME"] = exposure_time
    header["FR1CMD"] = fr1_commanded if fr1_commanded is not None else -9999.0
    header["FR1MEAS"] = fr1_measured if fr1_measured is not None else -9999.0
    header["FR3CMD"] = fr3_commanded if fr3_commanded is not None else -9999.0
    header["FR3MEAS"] = fr3_measured if fr3_measured is not None else -9999.0
    header["INSTRUME"] = instrument
    header["DETECTOR"] = detector
    header["SIMULATE"] = simulation
    header["QCFLAG"] = qc_flag or ("SIMULATION_ONLY" if simulation else "PASS")
    header["AXISMAP"] = axis_map[:68]
    header["POLCONT"] = "UNSUPPORTED" if instrument == "ESPADONS" else "UNVERIFIED"
    header["CHANMAP"] = "O_BEAM/E_BEAM" if mode.is_polarimetric else "TARGET/SKY/DISABLED"

    telemetry_rows = [
        (key[:32], json.dumps(value, default=str)[:128], "", "GOOD")
        for key, value in sorted(telemetry.items())
    ]
    provenance_rows = [
        ("COMMAND_ID", command_id, "", "GOOD"),
        ("CONFIG_SNAPSHOT_ID", config_snapshot_id, "", "UNVERIFIED"),
        ("SOFTWARE_COMMIT", settings.software_commit, "", "GOOD"),
    ]
    provenance_rows.extend(
        (
            key[:32],
            json.dumps(value, default=str)[:128],
            "",
            "GOOD",
        )
        for key, value in sorted((provenance or {}).items())
    )
    extensions: list[fits.hdu.base.ExtensionHDU] = [
        _text_table("TELEMETRY", telemetry_rows),
        _text_table("PROVENANCE", provenance_rows),
    ]
    if source_header:
        extensions.append(
            _text_table(
                "RAW_HEADER",
                [
                    (key[:32], json.dumps(value, default=str)[:128], "", "SOURCE")
                    for key, value in sorted(source_header.items())
                ],
            )
        )
    hdul = fits.HDUList(
        [primary, *extensions]
    )
    hdul.writeto(part_path, overwrite=False, checksum=True, output_verify="exception")
    validate_l0(part_path)
    fd = os.open(part_path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(part_path, final_path)
    dir_fd = os.open(final_path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    with fits.open(final_path, checksum=True) as committed:
        return str(committed[0].header["CHECKSUM"]), str(committed[0].header["DATASUM"])


def validate_l0(path: Path) -> None:
    try:
        with fits.open(path, checksum=True, memmap=False) as hdul:
            if hdul[0].data is None or hdul[0].data.ndim != 2:
                raise SpriteError("L0_SCHEMA_INVALID", "L0 primary HDU must be a 2D image")
            missing = sorted(REQUIRED_L0_KEYS - set(hdul[0].header))
            if missing:
                raise SpriteError(
                    "L0_SCHEMA_INVALID",
                    "required FITS keywords are missing",
                    details={"missing": missing},
                )
            names = {hdu.name for hdu in hdul}
            if not {"TELEMETRY", "PROVENANCE"}.issubset(names):
                raise SpriteError("L0_SCHEMA_INVALID", "required named HDUs are missing")
            for hdu in hdul:
                if hdu.verify_checksum() != 1 or hdu.verify_datasum() != 1:
                    raise SpriteError("L0_CHECKSUM_INVALID", "FITS checksum validation failed")
    except OSError as exc:
        raise SpriteError("L0_READ_FAILED", str(exc)) from exc
