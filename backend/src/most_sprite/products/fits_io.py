from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from most_sprite.config import get_settings
from most_sprite.domain.enums import DataMode
from most_sprite.pipeline.echelle.models import CalibrationFrame, SpectrumChannel, SpectrumSet
from most_sprite.pipeline.nonpolar import NonPolarProduct
from most_sprite.pipeline.polarimetry import PolarimetricProduct
from most_sprite.pipeline.simulation import channel_centers, channel_roles

COMMON_PRIMARY_KEYS = {
    "SCHEMVER",
    "PRODLEV",
    "DATAMODE",
    "STOKES",
    "NORMSTAT",
    "WAVETYPE",
    "SPECSYS",
    "TIMESYS",
    "SEQID",
    "CONFIGID",
    "PIPENAME",
    "PIPEVER",
    "SWCOMMIT",
    "CALVER",
    "CALSETID",
    "INSTRUME",
    "DETECTOR",
    "MODVER",
    "MUELLVER",
    "POLCONT",
    "QCFLAG",
    "CHECKSUM",
    "DATASUM",
}


def validate_science_fits(path: Path) -> None:
    with fits.open(path, checksum=True, memmap=False) as hdul:
        header = hdul[0].header
        missing = COMMON_PRIMARY_KEYS - set(header)
        if missing:
            raise ValueError(f"science product is missing primary keywords: {sorted(missing)}")
        for hdu in hdul:
            if hdu.verify_checksum() != 1 or hdu.verify_datasum() != 1:
                raise ValueError(f"checksum validation failed for {path}")
        level = str(header["PRODLEV"])
        mode = DataMode(str(header["DATAMODE"]))
        names = {hdu.name for hdu in hdul}
        if level == "L1" and not {"SCI", "VAR", "DQ"}.issubset(names):
            raise ValueError("L1 must contain SCI, VAR and DQ HDUs")
        if level == "L2":
            required_roles = set(channel_roles(mode))
            actual_roles = {
                str(hdu.header.get("CHANNEL_ROLE"))
                for hdu in hdul[1:]
                if hdu.header.get("CHANNEL_ROLE")
            }
            if actual_roles != required_roles:
                raise ValueError(
                    f"L2 channel roles differ: {actual_roles} != {required_roles}"
                )
            required_columns = {"ORDER", "PIXEL", "WAVE", "FLUX", "VAR", "DQ"}
            for hdu in hdul[1:]:
                columns = set(hdu.columns.names)
                if not required_columns.issubset(columns):
                    raise ValueError(
                        f"L2 channel {hdu.name} is missing columns: "
                        f"{sorted(required_columns - columns)}"
                    )
        if level == "L3":
            if "SPECTRUM" not in hdul:
                raise ValueError("L3 must contain a SPECTRUM table")
            columns = set(hdul["SPECTRUM"].columns.names)
            if mode.is_polarimetric:
                required = {
                    "WAVE",
                    "I",
                    "P",
                    "N1",
                    "N2",
                    "ERR_I",
                    "ERR_P",
                    "ERR_N1",
                    "ERR_N2",
                    "COV_P_N1",
                    "COV_P_N2",
                    "COV_N1_N2",
                    "DQ",
                }
            else:
                required = {
                    "WAVE",
                    "TARGET",
                    "SKY",
                    "ALPHA",
                    "I",
                    "ERR_TARGET",
                    "ERR_SKY",
                    "ERR_ALPHA",
                    "ERR_I",
                    "DQ",
                }
                forbidden = {
                    "P",
                    "N1",
                    "N2",
                    "ERR_P",
                    "ERR_N1",
                    "ERR_N2",
                    "COV_P_N1",
                    "COV_P_N2",
                    "COV_N1_N2",
                }
                if columns & forbidden:
                    raise ValueError("NONPOL L3 contains forbidden polarization columns")
            if not required.issubset(columns):
                raise ValueError(f"L3 is missing columns: {sorted(required - columns)}")


def _common_header(
    header: fits.Header,
    *,
    level: str,
    mode: DataMode,
    sequence_id: str,
    config_id: str,
    schema_version: str,
    instrument: str = "MOST",
    detector: str = "SIMULATOR",
    calibration_set_id: str = "NA",
    calibration_version: str = "SIMULATION-v1",
    modulation_version: str = "most-v1",
    wavelength_type: str = "UNVERIFIED",
    specsys: str = "TOPOCENT",
    normalization_status: str = "UNNORMALIZED",
    qc_flag: str = "SIMULATION_ONLY",
) -> None:
    settings = get_settings()
    header["SCHEMVER"] = schema_version
    header["PRODLEV"] = level
    header["DATAMODE"] = mode.value
    header["STOKES"] = mode.value[-1] if mode.is_polarimetric else "NA"
    header["NORMSTAT"] = normalization_status
    header["WAVETYPE"] = wavelength_type
    header["SPECSYS"] = specsys
    header["TIMESYS"] = "UTC"
    header["SEQID"] = sequence_id
    header["CONFIGID"] = config_id
    header["PIPENAME"] = "MOST-SPRITE"
    header["PIPEVER"] = settings.software_version
    header["SWCOMMIT"] = settings.software_commit
    header["INSTRUME"] = instrument
    header["DETECTOR"] = detector
    header["CALSETID"] = calibration_set_id
    header["CALVER"] = calibration_version
    header["MODVER"] = modulation_version
    header["MUELLVER"] = "UNAPPLIED"
    header["POLCONT"] = "UNSUPPORTED"
    header["QCFLAG"] = qc_flag


def _write_atomic(hdul: fits.HDUList, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        validate_science_fits(path)
        return
    part = path.with_suffix(path.suffix + ".part")
    if part.exists():
        part.unlink()
    hdul.writeto(part, checksum=True, output_verify="exception")
    validate_science_fits(part)
    fd = os.open(part, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(part, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_l1(
    frame: CalibrationFrame,
    path: Path,
    *,
    mode: DataMode,
    sequence_id: str,
    exposure_id: str,
    config_id: str,
    instrument: str = "MOST",
    detector: str = "SIMULATOR",
    calibration_set_id: str = "NA",
    calibration_version: str = "SIMULATION-v1",
    modulation_version: str = "most-v1",
    qc_flag: str = "SIMULATION_ONLY",
) -> None:
    primary = fits.PrimaryHDU()
    _common_header(
        primary.header,
        level="L1",
        mode=mode,
        sequence_id=sequence_id,
        config_id=config_id,
        schema_version="L1-v1",
        instrument=instrument,
        detector=detector,
        calibration_set_id=calibration_set_id,
        calibration_version=calibration_version,
        modulation_version=modulation_version,
        qc_flag=qc_flag,
    )
    primary.header["EXPID"] = exposure_id
    science = fits.ImageHDU(frame.data.astype(np.float32), name="SCI")
    science.header["BUNIT"] = frame.unit
    variance = fits.ImageHDU(frame.variance.astype(np.float32), name="VAR")
    variance.header["BUNIT"] = f"{frame.unit}2"
    dq = fits.ImageHDU(frame.dq.astype(np.uint32), name="DQ")
    _write_atomic(fits.HDUList([primary, science, variance, dq]), path)


def extract_simulation_channels(frame: CalibrationFrame, mode: DataMode) -> SpectrumSet:
    rows, columns = frame.data.shape
    centers = channel_centers(rows, mode)
    roles = channel_roles(mode)
    channels: dict[str, SpectrumChannel] = {}
    for role in roles:
        all_wave: list[np.ndarray] = []
        all_flux: list[np.ndarray] = []
        all_variance: list[np.ndarray] = []
        all_dq: list[np.ndarray] = []
        all_order: list[np.ndarray] = []
        all_pixel: list[np.ndarray] = []
        for order_index, center in enumerate(centers[role]):
            lower = max(0, int(np.floor(center - 4)))
            upper = min(rows, int(np.ceil(center + 5)))
            flux = np.nansum(frame.data[lower:upper], axis=0)
            variance = np.nansum(frame.variance[lower:upper], axis=0)
            dq = np.bitwise_or.reduce(frame.dq[lower:upper], axis=0, initial=0)
            all_wave.append(np.full(columns, np.nan, dtype=np.float64))
            all_flux.append(flux)
            all_variance.append(variance)
            all_dq.append(dq)
            all_order.append(np.full(columns, order_index, dtype=np.int32))
            all_pixel.append(np.arange(columns, dtype=np.float64))
        channels[role] = SpectrumChannel(
            role=role,
            order=np.concatenate(all_order),
            pixel=np.concatenate(all_pixel),
            wavelength=np.concatenate(all_wave),
            flux=np.concatenate(all_flux),
            variance=np.concatenate(all_variance),
            dq=np.concatenate(all_dq),
            unit=frame.unit,
            config_version=frame.config_version,
            provenance={
                "algorithm": "simulation_aperture_extract_v1",
                "wavelength_state": "UNCALIBRATED",
                "resampled": False,
            },
        )
    return SpectrumSet(
        channels=channels,
        native_grid=True,
        config_version=frame.config_version,
        provenance={"common_grid_resampling_count": 0, "simulation_geometry": True},
    )


def _channel_hdu(channel: SpectrumChannel) -> fits.BinTableHDU:
    columns = [
        fits.Column(name="ORDER", format="J", array=channel.order),
        fits.Column(name="PIXEL", format="D", unit="pixel", array=channel.pixel),
        fits.Column(name="WAVE", format="D", unit="nm", array=channel.wavelength),
        fits.Column(name="FLUX", format="D", unit=channel.unit, array=channel.flux),
        fits.Column(name="VAR", format="D", unit=f"{channel.unit}2", array=channel.variance),
        fits.Column(name="DQ", format="J", array=channel.dq.astype(np.int32)),
    ]
    if channel.covariance_lag1 is not None:
        columns.append(
            fits.Column(
                name="COV_LAG1",
                format="D",
                unit=f"{channel.unit}2",
                array=channel.covariance_lag1,
            )
        )
    hdu = fits.BinTableHDU.from_columns(columns, name=channel.role)
    hdu.header["HIERARCH CHANNEL_ROLE"] = channel.role
    return hdu


def write_l2(
    spectra: SpectrumSet,
    path: Path,
    *,
    mode: DataMode,
    sequence_id: str,
    exposure_id: str,
    config_id: str,
    instrument: str = "MOST",
    detector: str = "SIMULATOR",
    calibration_set_id: str = "NA",
    calibration_version: str = "SIMULATION-v1",
    modulation_version: str = "most-v1",
    wavelength_type: str = "UNVERIFIED",
    qc_flag: str = "SIMULATION_ONLY",
) -> None:
    primary = fits.PrimaryHDU()
    _common_header(
        primary.header,
        level="L2",
        mode=mode,
        sequence_id=sequence_id,
        config_id=config_id,
        schema_version="L2-v1",
        instrument=instrument,
        detector=detector,
        calibration_set_id=calibration_set_id,
        calibration_version=calibration_version,
        modulation_version=modulation_version,
        wavelength_type=wavelength_type,
        qc_flag=qc_flag,
    )
    primary.header["EXPID"] = exposure_id
    primary.header["RESAMPN"] = int(spectra.provenance.get("common_grid_resampling_count", 0))
    _write_atomic(
        fits.HDUList([primary, *[_channel_hdu(channel) for channel in spectra.channels.values()]]),
        path,
    )


def write_polar_l3(
    product: PolarimetricProduct,
    path: Path,
    *,
    mode: DataMode,
    sequence_id: str,
    group_id: str,
    config_id: str,
    exposure_rows: list[dict[str, Any]],
    instrument: str = "MOST",
    detector: str = "SIMULATOR",
    calibration_set_id: str = "NA",
    calibration_version: str = "SIMULATION-v1",
    modulation_version: str = "most-v1",
    wavelength_type: str = "UNVERIFIED",
    specsys: str = "TOPOCENT",
    normalization_status: str = "UNNORMALIZED",
    qc_flag: str = "SIMULATION_ONLY",
) -> None:
    def optional_float_column(name: str) -> np.ndarray:
        return np.asarray(
            [
                np.nan if row.get(name) is None else float(row[name])
                for row in exposure_rows
            ],
            dtype=np.float64,
        )

    primary = fits.PrimaryHDU()
    _common_header(
        primary.header,
        level="L3",
        mode=mode,
        sequence_id=sequence_id,
        config_id=config_id,
        schema_version="L3-v1",
        instrument=instrument,
        detector=detector,
        calibration_set_id=calibration_set_id,
        calibration_version=calibration_version,
        modulation_version=modulation_version,
        wavelength_type=wavelength_type,
        specsys=specsys,
        normalization_status=normalization_status,
        qc_flag=qc_flag,
    )
    primary.header["GROUPID"] = group_id
    spectrum = fits.BinTableHDU.from_columns(
        [
            fits.Column(
                name="WAVE",
                format="D",
                unit=product.wavelength_unit,
                array=product.wavelength,
            ),
            fits.Column(name="I", format="D", unit=product.intensity_unit, array=product.intensity),
            fits.Column(
                name="P", format="D", unit=product.polarization_unit, array=product.polarization
            ),
            fits.Column(
                name="N1", format="D", unit=product.polarization_unit, array=product.null1
            ),
            fits.Column(
                name="N2", format="D", unit=product.polarization_unit, array=product.null2
            ),
            fits.Column(
                name="ERR_I", format="D", unit=product.intensity_unit, array=product.err_intensity
            ),
            fits.Column(
                name="ERR_P",
                format="D",
                unit=product.polarization_unit,
                array=product.err_polarization,
            ),
            fits.Column(
                name="ERR_N1",
                format="D",
                unit=product.polarization_unit,
                array=product.err_null1,
            ),
            fits.Column(
                name="ERR_N2",
                format="D",
                unit=product.polarization_unit,
                array=product.err_null2,
            ),
            fits.Column(name="COV_P_N1", format="D", array=product.covariance_p_null1),
            fits.Column(name="COV_P_N2", format="D", array=product.covariance_p_null2),
            fits.Column(name="COV_N1_N2", format="D", array=product.covariance_null1_null2),
            fits.Column(name="DIFFCHECK", format="D", array=product.difference_check),
            fits.Column(name="DQ", format="J", array=product.dq.astype(np.int32)),
        ],
        name="SPECTRUM",
    )
    sequence = fits.BinTableHDU.from_columns(
        [
            fits.Column(
                name="EXPID", format="36A", array=[row["exposure_id"] for row in exposure_rows]
            ),
            fits.Column(
                name="SUBIDX", format="J", array=[row["sub_index"] for row in exposure_rows]
            ),
            fits.Column(
                name="FR1CMD",
                format="D",
                unit="deg",
                array=optional_float_column("fr1_cmd"),
            ),
            fits.Column(
                name="FR1MEAS",
                format="D",
                unit="deg",
                array=optional_float_column("fr1_meas"),
            ),
            fits.Column(
                name="FR3CMD",
                format="D",
                unit="deg",
                array=optional_float_column("fr3_cmd"),
            ),
            fits.Column(
                name="FR3MEAS",
                format="D",
                unit="deg",
                array=optional_float_column("fr3_meas"),
            ),
            fits.Column(name="BEAMMAP", format="24A", array=["O_BEAM/E_BEAM"] * 4),
        ],
        name="SEQUENCE",
    )
    provenance = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="NAME", format="32A", array=["CONFIG", "ALGORITHM"]),
            fits.Column(name="VALUE", format="72A", array=[config_id, "ratio-log-v1"]),
        ],
        name="PROVENANCE",
    )
    covariance_columns: list[fits.Column] = []
    for name, values in (
        ("I_LAG1", product.covariance_lag1_intensity),
        ("P_LAG1", product.covariance_lag1_polarization),
        ("N1_LAG1", product.covariance_lag1_null1),
        ("N2_LAG1", product.covariance_lag1_null2),
    ):
        if values is not None:
            covariance_columns.append(fits.Column(name=name, format="D", array=values))
    hdus: list[fits.hdu.base.ExtensionHDU] = [primary, spectrum, sequence, provenance]
    if covariance_columns:
        covariance = fits.BinTableHDU.from_columns(
            covariance_columns, name="RESAMPLE_COVARIANCE"
        )
        covariance.header["COVTYPE"] = "ADJACENT_PIXEL_LAG1"
        covariance.header["RESAMPN"] = 1
        hdus.append(covariance)
    _write_atomic(fits.HDUList(hdus), path)


def write_nonpolar_l3(
    product: NonPolarProduct,
    path: Path,
    *,
    sequence_id: str,
    exposure_id: str,
    config_id: str,
) -> None:
    primary = fits.PrimaryHDU()
    _common_header(
        primary.header,
        level="L3",
        mode=DataMode.NONPOL,
        sequence_id=sequence_id,
        config_id=config_id,
        schema_version="L3-v1",
    )
    primary.header["EXPID"] = exposure_id
    primary.header["SKYSUB"] = product.background_subtracted
    spectrum = fits.BinTableHDU.from_columns(
        [
            fits.Column(
                name="WAVE",
                format="D",
                unit=product.wavelength_unit,
                array=product.wavelength,
            ),
            fits.Column(name="TARGET", format="D", unit=product.flux_unit, array=product.target),
            fits.Column(name="SKY", format="D", unit=product.flux_unit, array=product.sky),
            fits.Column(name="ALPHA", format="D", array=product.alpha),
            fits.Column(name="I", format="D", unit=product.flux_unit, array=product.intensity),
            fits.Column(
                name="ERR_TARGET", format="D", unit=product.flux_unit, array=product.err_target
            ),
            fits.Column(name="ERR_SKY", format="D", unit=product.flux_unit, array=product.err_sky),
            fits.Column(name="ERR_ALPHA", format="D", array=product.err_alpha),
            fits.Column(
                name="ERR_I", format="D", unit=product.flux_unit, array=product.err_intensity
            ),
            fits.Column(name="DQ", format="J", array=product.dq.astype(np.int32)),
        ],
        name="SPECTRUM",
    )
    provenance = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="NAME", format="32A", array=["CONFIG", "CHANNEL_MAP"]),
            fits.Column(name="VALUE", format="72A", array=[config_id, "TARGET/SKY/DISABLED"]),
        ],
        name="PROVENANCE",
    )
    _write_atomic(fits.HDUList([primary, spectrum, provenance]), path)
