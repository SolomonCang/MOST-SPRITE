"""Immutable FITS serialization for an ESPaDOnS ``CalibrationSet``."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from most_sprite.pipeline.echelle.espadons import ESPaDOnSTraceSet
from most_sprite.pipeline.echelle.models import CalibrationFrame, TraceModel, WavelengthSolution


@dataclass(slots=True)
class ESPaDOnSCalibrationBundle:
    master_bias: CalibrationFrame
    master_flat: CalibrationFrame
    flat_response: np.ndarray
    flat_variance: np.ndarray
    flat_dq: np.ndarray
    spatial_profile: np.ndarray
    trace_set: ESPaDOnSTraceSet
    wavelength_solution: WavelengthSolution
    blaze: dict[str, dict[int, np.ndarray]]
    identified_lines: list[dict[str, float | int | str]]
    qc: dict[str, Any]
    provenance: dict[str, Any]


def _json_hdu(name: str, value: object) -> fits.BinTableHDU:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    width = max(1, len(encoded.encode("utf-8")))
    return fits.BinTableHDU.from_columns(
        [fits.Column(name="JSON", format=f"{width}A", array=[encoded])], name=name
    )


def _trace_hdu(trace_set: ESPaDOnSTraceSet) -> fits.BinTableHDU:
    orders = trace_set.combined.order_ids
    columns = [fits.Column(name="ORDER", format="J", array=orders)]
    for name, trace in (
        ("COMBINED", trace_set.combined),
        ("O_BEAM", trace_set.beams["O_BEAM"]),
        ("E_BEAM", trace_set.beams["E_BEAM"]),
    ):
        width = trace.coefficients.shape[1]
        columns.extend(
            [
                fits.Column(
                    name=f"{name}_COEFF", format=f"{width}D", array=trace.coefficients
                ),
                fits.Column(name=f"{name}_WIDTH", format="D", array=trace.widths),
            ]
        )
    hdu = fits.BinTableHDU.from_columns(columns, name="TRACE")
    hdu.header["TRACVER"] = trace_set.config_version
    return hdu


def _wavelength_hdu(solution: WavelengthSolution) -> fits.BinTableHDU:
    orders = np.asarray(sorted(solution.coefficients), dtype=np.int32)
    coefficient_count = max(len(solution.coefficients[int(order)]) for order in orders)

    def padded(role: str | None) -> np.ndarray:
        rows: list[np.ndarray] = []
        source = (
            solution.coefficients
            if role is None
            else solution.channel_coefficients.get(role, solution.coefficients)
        )
        for order in orders:
            values = np.asarray(source[int(order)], dtype=np.float64)
            rows.append(np.pad(values, (coefficient_count - values.size, 0)))
        return np.asarray(rows)

    hdu = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="ORDER", format="J", array=orders),
            fits.Column(name="COEFF", format=f"{coefficient_count}D", array=padded(None)),
            fits.Column(
                name="O_BEAM_COEFF", format=f"{coefficient_count}D", array=padded("O_BEAM")
            ),
            fits.Column(
                name="E_BEAM_COEFF", format=f"{coefficient_count}D", array=padded("E_BEAM")
            ),
            fits.Column(
                name="RMS_M_S",
                format="D",
                array=[solution.residual_rms.get(int(order), np.nan) for order in orders],
            ),
        ],
        name="WAVELENGTH",
    )
    hdu.header["WAVETYPE"] = solution.wavelength_type
    hdu.header["CUNIT1"] = solution.unit
    hdu.header["WAVECFG"] = solution.config_version
    return hdu


def _blaze_hdu(blaze: dict[str, dict[int, np.ndarray]]) -> fits.BinTableHDU:
    roles: list[str] = []
    orders: list[int] = []
    values: list[np.ndarray] = []
    for role, by_order in sorted(blaze.items()):
        for order, flux in sorted(by_order.items(), reverse=True):
            roles.append(role)
            orders.append(order)
            values.append(np.asarray(flux, dtype=np.float32))
    width = max((value.size for value in values), default=1)
    padded = np.full((len(values), width), np.nan, dtype=np.float32)
    for index, value in enumerate(values):
        padded[index, : value.size] = value
    return fits.BinTableHDU.from_columns(
        [
            fits.Column(name="ROLE", format="16A", array=roles),
            fits.Column(name="ORDER", format="J", array=orders),
            fits.Column(name="BLAZE", format=f"{width}E", array=padded),
        ],
        name="BLAZE",
    )


def _identified_hdu(lines: list[dict[str, float | int | str]]) -> fits.BinTableHDU:
    return fits.BinTableHDU.from_columns(
        [
            fits.Column(name="ORDER", format="J", array=[int(row["order"]) for row in lines]),
            fits.Column(name="PIXEL", format="D", array=[float(row["pixel"]) for row in lines]),
            fits.Column(
                name="WAVE_NM",
                format="D",
                array=[float(row["wavelength_nm"]) for row in lines],
            ),
            fits.Column(
                name="RESID_M_S",
                format="D",
                array=[float(row["residual_m_s"]) for row in lines],
            ),
            fits.Column(
                name="USED", format="L", array=[bool(row["used"]) for row in lines]
            ),
        ],
        name="IDENTIFIED_LINES",
    )


def _verify(path: Path) -> None:
    with fits.open(path, checksum=True, memmap=False) as hdul:
        required = {
            "MASTER_BIAS",
            "BIAS_VAR",
            "BIAS_DQ",
            "MASTER_FLAT",
            "FLAT_VAR",
            "FLAT_DQ",
            "FLAT_RESPONSE",
            "RESPONSE_VAR",
            "RESPONSE_DQ",
            "SPATIAL_PROFILE",
            "TRACE",
            "WAVELENGTH",
            "BLAZE",
            "IDENTIFIED_LINES",
            "QC",
            "PROVENANCE",
        }
        missing = required - {hdu.name for hdu in hdul}
        if missing:
            raise ValueError(f"calibration bundle is missing HDUs: {sorted(missing)}")
        for hdu in hdul:
            # Astropy's CompImageHDU reports 2 when the compressed image has no
            # per-extension FITS checksum.  The immutable bundle is protected
            # by its manifest SHA-256; any present FITS checksum must still pass.
            if hdu.verify_checksum() == 0 or hdu.verify_datasum() == 0:
                raise ValueError(f"calibration checksum failed for {path}")


def write_calibration_bundle(bundle: ESPaDOnSCalibrationBundle, path: Path) -> None:
    header = fits.Header()
    header["INSTRUME"] = "ESPADONS"
    header["DETECTOR"] = "OLAPA"
    header["CALTYPE"] = "CALIBRATION_SET"
    header["CALVER"] = bundle.trace_set.config_version
    header["WAVETYPE"] = bundle.wavelength_solution.wavelength_type
    header["SPECSYS"] = "TOPOCENT"
    hdus: list[fits.hdu.base.ExtensionHDU] = [fits.PrimaryHDU(header=header)]
    for name, values in (
        ("MASTER_BIAS", bundle.master_bias.data),
        ("BIAS_VAR", bundle.master_bias.variance),
        ("BIAS_DQ", bundle.master_bias.dq),
        ("MASTER_FLAT", bundle.master_flat.data),
        ("FLAT_VAR", bundle.master_flat.variance),
        ("FLAT_DQ", bundle.master_flat.dq),
        ("FLAT_RESPONSE", bundle.flat_response),
        ("RESPONSE_VAR", bundle.flat_variance),
        ("RESPONSE_DQ", bundle.flat_dq),
        ("SPATIAL_PROFILE", bundle.spatial_profile),
    ):
        array = np.asarray(values)
        if array.dtype.kind == "f":
            array = array.astype(np.float32)
        elif array.dtype.kind in "ui":
            array = array.astype(np.uint32)
        hdus.append(fits.CompImageHDU(data=array, name=name, compression_type="RICE_1"))
    hdus.extend(
        [
            _trace_hdu(bundle.trace_set),
            _wavelength_hdu(bundle.wavelength_solution),
            _blaze_hdu(bundle.blaze),
            _identified_hdu(bundle.identified_lines),
            _json_hdu("QC", bundle.qc),
            _json_hdu("PROVENANCE", bundle.provenance),
        ]
    )
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        _verify(target)
        return
    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)
    fits.HDUList(hdus).writeto(part, checksum=True, output_verify="exception")
    _verify(part)
    with part.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(part, target)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_json(hdul: fits.HDUList, name: str) -> dict[str, Any]:
    value = hdul[name].data["JSON"][0]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    result: dict[str, Any] = json.loads(str(value).rstrip())
    return result


def read_calibration_bundle(path: Path) -> ESPaDOnSCalibrationBundle:
    _verify(path)
    with fits.open(path, checksum=True, memmap=False) as hdul:
        trace_table = hdul["TRACE"].data
        orders = np.asarray(trace_table["ORDER"], dtype=np.int32)

        def trace(role: str, width_name: str | None = None) -> TraceModel:
            prefix = role
            return TraceModel(
                order_ids=orders.copy(),
                coefficients=np.asarray(trace_table[f"{prefix}_COEFF"], dtype=np.float64),
                widths=np.asarray(
                    trace_table[f"{width_name or prefix}_WIDTH"], dtype=np.float64
                ),
                config_version=str(hdul["TRACE"].header["TRACVER"]),
                provenance={"loaded_from": str(path), "role": role},
            )

        trace_set = ESPaDOnSTraceSet(
            combined=trace("COMBINED"),
            beams={"O_BEAM": trace("O_BEAM"), "E_BEAM": trace("E_BEAM")},
            config_version=str(hdul["TRACE"].header["TRACVER"]),
            provenance={"loaded_from": str(path)},
        )
        wavelength_table = hdul["WAVELENGTH"].data
        base: dict[int, np.ndarray] = {}
        by_role: dict[str, dict[int, np.ndarray]] = {"O_BEAM": {}, "E_BEAM": {}}
        rms: dict[int, float] = {}
        for row in wavelength_table:
            order = int(row["ORDER"])
            base[order] = np.asarray(row["COEFF"], dtype=np.float64)
            by_role["O_BEAM"][order] = np.asarray(row["O_BEAM_COEFF"], dtype=np.float64)
            by_role["E_BEAM"][order] = np.asarray(row["E_BEAM_COEFF"], dtype=np.float64)
            rms[order] = float(row["RMS_M_S"])
        solution = WavelengthSolution(
            coefficients=base,
            residual_rms=rms,
            channel_coefficients=by_role,
            channel_residual_rms={role: rms.copy() for role in by_role},
            wavelength_type=str(hdul["WAVELENGTH"].header["WAVETYPE"]),
            unit=str(hdul["WAVELENGTH"].header["CUNIT1"]),
            config_version=str(hdul["WAVELENGTH"].header["WAVECFG"]),
            provenance={"loaded_from": str(path)},
        )
        blaze: dict[str, dict[int, np.ndarray]] = {}
        for row in hdul["BLAZE"].data:
            role_value = row["ROLE"]
            role = (
                role_value.decode("ascii").strip()
                if isinstance(role_value, bytes)
                else str(role_value).strip()
            )
            blaze.setdefault(role, {})[int(row["ORDER"])] = np.asarray(
                row["BLAZE"], dtype=np.float64
            )
        lines: list[dict[str, float | int | str]] = [
            {
                "order": int(row["ORDER"]),
                "pixel": float(row["PIXEL"]),
                "wavelength_nm": float(row["WAVE_NM"]),
                "residual_m_s": float(row["RESID_M_S"]),
                "used": bool(row["USED"]),
            }
            for row in hdul["IDENTIFIED_LINES"].data
        ]

        def frame(prefix: str) -> CalibrationFrame:
            return CalibrationFrame(
                data=np.asarray(hdul[prefix].data, dtype=np.float64),
                variance=np.asarray(hdul[f"{prefix.split('_')[-1]}_VAR"].data, dtype=np.float64),
                dq=np.asarray(hdul[f"{prefix.split('_')[-1]}_DQ"].data, dtype=np.uint32),
                unit="electron",
                config_version=trace_set.config_version,
                provenance={"loaded_from": str(path)},
            )

        return ESPaDOnSCalibrationBundle(
            master_bias=frame("MASTER_BIAS"),
            master_flat=frame("MASTER_FLAT"),
            flat_response=np.asarray(hdul["FLAT_RESPONSE"].data, dtype=np.float64),
            flat_variance=np.asarray(hdul["RESPONSE_VAR"].data, dtype=np.float64),
            flat_dq=np.asarray(hdul["RESPONSE_DQ"].data, dtype=np.uint32),
            spatial_profile=np.asarray(hdul["SPATIAL_PROFILE"].data, dtype=np.float64),
            trace_set=trace_set,
            wavelength_solution=solution,
            blaze=blaze,
            identified_lines=lines,
            qc=_read_json(hdul, "QC"),
            provenance=_read_json(hdul, "PROVENANCE"),
        )
