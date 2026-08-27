"""Automatic OLAPA ThAr wavelength calibration.

The global two-dimensional fit follows the wavelength-calibration
responsibilities in GAMSE's ``echelle/wlcalib.py`` at frozen commit
4d91ead6d8380b75a5a445c2dae78429bc23e0c9.  This implementation is independent
of GAMSE types and imports.  It uses a deterministic physical OLAPA bootstrap,
requires coincident lines in both polarimetric beams, and never substitutes a
simulated wavelength scale when identification fails.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import find_peaks

from most_sprite.errors import SpriteError
from most_sprite.pipeline.echelle.models import SpectrumSet, WavelengthSolution

_LIGHT_SPEED_M_S = 299_792_458.0
_SOURCE_COMMIT = "4d91ead6d8380b75a5a445c2dae78429bc23e0c9"
_BOOTSTRAP_REFERENCE = {
    "file_id": "2495167c",
    "md5": "4a030086d401540004a14fb607795ad2",
    "sha256": "7c9cc8dae64dcfa677ac921e96a5ee3f04c02415f6fcdcc63db5727a005e3ce6",
}
# Degree-two fit of m*lambda to the immutable GAMSE OLAPA reference lamp,
# expressed in this module's normalized (pixel, order) coordinates and
# _powers(2) ordering.  It is only an identification bootstrap: every output
# coefficient is re-fit from the selected same-night ThAr exposure.
_BOOTSTRAP_COEFFICIENTS = np.asarray(
    [
        22643.82942575951,
        908.0067373985538,
        -147.0939726089756,
        -1.551829830541917,
        4.615527053413751,
        -0.421869421884266,
    ],
    dtype=np.float64,
)


@dataclass(frozen=True, slots=True)
class ESPaDOnSWavelengthCalibration:
    solution: WavelengthSolution
    qc: dict[str, Any]
    identified_lines: list[dict[str, float | int | str]]


def _line_list_path() -> Path:
    return (
        Path(__file__).parents[1]
        / "instruments"
        / "data"
        / "thar_espadons_air.csv"
    )


def load_espadons_thar_lines() -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    wavelengths: list[float] = []
    intensities: list[float] = []
    with _line_list_path().open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            wavelengths.append(float(row["wavelength_nm"]))
            intensities.append(float(row["intensity"]))
    order = np.argsort(wavelengths)
    return (
        np.asarray(wavelengths, dtype=np.float64)[order],
        np.asarray(intensities, dtype=np.float64)[order],
    )


def _continuum_removed(flux: NDArray[np.float64]) -> NDArray[np.float64]:
    values = np.asarray(flux, dtype=np.float64).copy()
    finite = np.isfinite(values)
    if finite.sum() < values.size // 2:
        return np.zeros(values.shape, dtype=np.float64)
    values[~finite] = np.nanmedian(values[finite])
    residual = np.clip(values - median_filter(values, 101, mode="nearest"), 0.0, None)
    scale = float(np.percentile(residual, 99.0))
    if not np.isfinite(scale) or scale <= 0:
        return np.zeros(values.shape, dtype=np.float64)
    return gaussian_filter1d(residual / scale, 0.7)


def _quadratic_centroid(signal: NDArray[np.float64], peak: int) -> float:
    if peak <= 0 or peak >= signal.size - 1:
        return float(peak)
    denominator = signal[peak - 1] - 2 * signal[peak] + signal[peak + 1]
    if denominator == 0:
        return float(peak)
    offset = 0.5 * (signal[peak - 1] - signal[peak + 1]) / denominator
    return float(peak + np.clip(offset, -1.0, 1.0))


def _coincident_peaks(
    spectra: SpectrumSet, order: int
) -> tuple[NDArray[np.float64], NDArray[np.float64], dict[str, float]]:
    signals: dict[str, NDArray[np.float64]] = {}
    peaks: dict[str, NDArray[np.int64]] = {}
    for role in ("O_BEAM", "E_BEAM"):
        channel = spectra.channels.get(role)
        if channel is None:
            raise SpriteError(
                "CALIBRATION_MISSING",
                "OLAPA ThAr calibration requires O_BEAM and E_BEAM extractions",
            )
        signal = _continuum_removed(channel.flux[channel.order == order])
        detected, _ = find_peaks(signal, prominence=0.025, distance=3)
        signals[role] = signal
        peaks[role] = detected
    o_peaks = peaks["O_BEAM"]
    e_peaks = peaks["E_BEAM"]
    if o_peaks.size == 0 or e_peaks.size < 2:
        return np.array([]), np.array([]), {"O_BEAM": 0.0, "E_BEAM": 0.0}
    right = np.clip(np.searchsorted(e_peaks, o_peaks), 1, e_peaks.size - 1)
    e_index = np.where(
        np.abs(e_peaks[right] - o_peaks) < np.abs(e_peaks[right - 1] - o_peaks),
        right,
        right - 1,
    )
    e_matched = e_peaks[e_index]
    coincident = np.abs(e_matched - o_peaks) <= 1
    o_selected = o_peaks[coincident]
    e_selected = e_matched[coincident]
    strength = np.minimum(
        signals["O_BEAM"][o_selected], signals["E_BEAM"][e_selected]
    )
    strong = strength > 0.04
    o_selected = o_selected[strong]
    e_selected = e_selected[strong]
    strength = strength[strong]
    o_centers = np.asarray(
        [_quadratic_centroid(signals["O_BEAM"], int(value)) for value in o_selected]
    )
    e_centers = np.asarray(
        [_quadratic_centroid(signals["E_BEAM"], int(value)) for value in e_selected]
    )
    centers = (o_centers + e_centers) / 2.0
    role_offsets = {
        "O_BEAM": float(np.median(o_centers - centers)) if centers.size else 0.0,
        "E_BEAM": float(np.median(e_centers - centers)) if centers.size else 0.0,
    }
    return centers, strength, role_offsets


def _powers(degree: int) -> list[tuple[int, int]]:
    return [
        (pixel_power, order_power)
        for order_power in range(degree + 1)
        for pixel_power in range(degree + 1 - order_power)
    ]


def _features(
    pixel: NDArray[np.float64], order: NDArray[np.float64], degree: int
) -> NDArray[np.float64]:
    return np.column_stack(
        [pixel**pixel_power * order**order_power for pixel_power, order_power in _powers(degree)]
    )


def _expand_coefficients(
    coefficients: NDArray[np.float64], old_degree: int, new_degree: int
) -> NDArray[np.float64]:
    values = dict(zip(_powers(old_degree), coefficients, strict=True))
    return np.asarray([values.get(power, 0.0) for power in _powers(new_degree)])


def _ransac_fit(
    records: NDArray[np.float64],
    *,
    degree: int,
    threshold_m_lambda_nm: float,
    trials: int,
    rng: np.random.Generator,
    pixel_count: int,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    pixel_midpoint = (pixel_count - 1) / 2.0
    pixel = (records[:, 1] - pixel_midpoint) / pixel_count
    order_coordinate = (records[:, 0] - 41.5) / 19.5
    design = _features(pixel, order_coordinate, degree)
    target = records[:, 0] * records[:, 2]
    parameter_count = design.shape[1]
    if records.shape[0] < parameter_count + 3:
        raise SpriteError(
            "CALIBRATION_MISSING",
            "too few unambiguous ThAr lines for the requested global fit",
            details={"line_count": int(records.shape[0]), "parameters": parameter_count},
        )
    best_count = 0
    best_mask: NDArray[np.bool_] | None = None
    for _ in range(trials):
        indices = rng.choice(records.shape[0], parameter_count, replace=False)
        try:
            coefficients = np.linalg.solve(design[indices], target[indices])
        except np.linalg.LinAlgError:
            continue
        mask = np.abs(target - design @ coefficients) < threshold_m_lambda_nm
        count = int(mask.sum())
        if count > best_count:
            best_count = count
            best_mask = mask
    if best_mask is None:
        raise SpriteError("CALIBRATION_MISSING", "ThAr global fit did not converge")
    mask = best_mask
    for _ in range(12):
        coefficients = np.linalg.lstsq(design[mask], target[mask], rcond=None)[0]
        residual = target - design @ coefficients
        center = float(np.median(residual[mask]))
        updated = np.abs(residual - center) < threshold_m_lambda_nm
        if np.array_equal(updated, mask):
            break
        mask = updated
    return coefficients, mask


def solve_espadons_thar(spectra: SpectrumSet) -> ESPaDOnSWavelengthCalibration:
    """Identify coincident OLAPA ThAr lines and fit a 2-D air-wavelength model."""
    if spectra.config_version != "espadons-olapa-v1":
        raise SpriteError(
            "CALIBRATION_MISMATCH",
            "the OLAPA wavelength solver received another detector configuration",
        )
    reference = spectra.channels.get("O_BEAM")
    if reference is None:
        raise SpriteError("CALIBRATION_MISSING", "O_BEAM arc extraction is missing")
    orders = sorted((int(value) for value in np.unique(reference.order)), reverse=True)
    pixel_count = int(np.max(reference.pixel)) + 1
    pixel_midpoint = (pixel_count - 1) / 2.0
    pixels = np.arange(pixel_count, dtype=np.float64)
    normalized_pixels = (pixels - pixel_midpoint) / pixel_count
    wavelengths, intensities = load_espadons_thar_lines()
    peak_data: dict[int, tuple[NDArray[np.float64], NDArray[np.float64]]] = {}
    role_offsets: dict[str, list[float]] = {"O_BEAM": [], "E_BEAM": []}
    for order in orders:
        centers, strength, offsets = _coincident_peaks(spectra, order)
        peak_data[order] = (centers, strength)
        for role in role_offsets:
            role_offsets[role].append(offsets[role])

    degree = 2
    coefficients = _BOOTSTRAP_COEFFICIENTS.copy()
    rng = np.random.default_rng(5)
    stages = (
        (14.0, 0.50, 2, 30_000),
        (8.0, 0.30, 2, 30_000),
        (5.0, 0.20, 2, 50_000),
        (3.0, 0.12, 2, 80_000),
        (2.0, 0.08, 3, 120_000),
        (1.2, 0.05, 3, 120_000),
        (0.8, 0.020, 3, 120_000),
    )
    final_records: NDArray[np.float64] | None = None
    final_mask: NDArray[np.bool_] | None = None
    for radius, threshold, new_degree, trials in stages:
        if new_degree != degree:
            coefficients = _expand_coefficients(coefficients, degree, new_degree)
            degree = new_degree
        records: list[tuple[float, float, float, float, float]] = []
        for order in orders:
            order_coordinate = np.full(pixel_count, (order - 41.5) / 19.5)
            model_m_lambda = _features(
                normalized_pixels, order_coordinate, degree
            ) @ coefficients
            in_order = (order * wavelengths <= np.max(model_m_lambda)) & (
                order * wavelengths >= np.min(model_m_lambda)
            )
            line_wavelength = wavelengths[in_order]
            line_intensity = intensities[in_order]
            if line_wavelength.size < 2:
                continue
            if not np.all(np.diff(model_m_lambda) > 0):
                raise SpriteError(
                    "CALIBRATION_MISMATCH",
                    "OLAPA wavelength bootstrap must increase along canonical dispersion pixels",
                )
            predicted = np.interp(
                order * line_wavelength,
                model_m_lambda,
                pixels,
            )
            detected, strength = peak_data[order]
            if detected.size == 0:
                continue
            right = np.clip(np.searchsorted(predicted, detected), 1, predicted.size - 1)
            selected = np.where(
                np.abs(predicted[right] - detected)
                < np.abs(predicted[right - 1] - detected),
                right,
                right - 1,
            )
            separation = detected - predicted[selected]
            accepted = np.abs(separation) < radius
            records.extend(
                (
                    float(order),
                    float(peak),
                    float(line_wavelength[line_index]),
                    float(line_intensity[line_index]),
                    float(line_strength),
                )
                for peak, line_index, line_strength in zip(
                    detected[accepted],
                    selected[accepted],
                    strength[accepted],
                    strict=True,
                )
            )
        record_array = np.asarray(records, dtype=np.float64)
        coefficients, mask = _ransac_fit(
            record_array,
            degree=degree,
            threshold_m_lambda_nm=threshold,
            trials=trials,
            rng=rng,
            pixel_count=pixel_count,
        )
        final_records = record_array
        final_mask = mask

    assert final_records is not None and final_mask is not None
    pixel_coordinate = (final_records[:, 1] - pixel_midpoint) / pixel_count
    order_coordinate = (final_records[:, 0] - 41.5) / 19.5
    design = _features(pixel_coordinate, order_coordinate, degree)
    residual_m_lambda = final_records[:, 0] * final_records[:, 2] - design @ coefficients
    residual_nm = residual_m_lambda / final_records[:, 0]
    residual_velocity = (
        _LIGHT_SPEED_M_S * residual_nm / final_records[:, 2]
    )
    used_velocity = residual_velocity[final_mask]
    rms_m_s = float(np.sqrt(np.mean(used_velocity**2)))
    used_orders = sorted({int(value) for value in final_records[final_mask, 0]})
    # The ten-coefficient degree-three surface must be strongly
    # over-constrained in both dimensions.  A wrong order/orientation can
    # produce a deceptively small residual from a few accidental aliases, so
    # require hundreds of same-night ThAr associations spanning 75% of OLAPA.
    # Remaining edge orders may be interpolated by the global physical
    # m-lambda surface; external golden-data residuals remain the release gate
    # for absolute accuracy.
    minimum_lines = 200
    minimum_orders = max(30, int(np.ceil(0.75 * len(orders))))
    if final_mask.sum() < minimum_lines or len(used_orders) < minimum_orders:
        raise SpriteError(
            "CALIBRATION_MISSING",
            "ThAr identification did not cover enough OLAPA orders",
            details={
                "line_count": int(final_mask.sum()),
                "minimum_line_count": minimum_lines,
                "order_count": len(used_orders),
                "minimum_order_count": minimum_orders,
            },
        )

    base_coefficients: dict[int, NDArray[np.float64]] = {}
    channel_coefficients: dict[str, dict[int, NDArray[np.float64]]] = {
        "O_BEAM": {},
        "E_BEAM": {},
    }
    per_order_rms: dict[int, float] = {}
    for order in orders:
        order_array = np.full(pixel_count, (order - 41.5) / 19.5)
        wavelength_grid = (
            _features(normalized_pixels, order_array, degree) @ coefficients / order
        )
        polynomial = np.polyfit(pixels, wavelength_grid, 3)
        base_coefficients[order] = polynomial
        selection = final_mask & (final_records[:, 0] == order)
        per_order_rms[order] = (
            float(np.sqrt(np.mean(residual_velocity[selection] ** 2)))
            if np.any(selection)
            else float("nan")
        )
        for role in channel_coefficients:
            offset = float(np.median(role_offsets[role]))
            channel_coefficients[role][order] = np.polyfit(
                pixels, np.polyval(polynomial, pixels - offset), 3
            )

    identified: list[dict[str, float | int | str]] = [
        {
            "order": int(row[0]),
            "pixel": float(row[1]),
            "wavelength_nm": float(row[2]),
            "intensity": float(row[3]),
            "residual_m_s": float(velocity),
            "used": bool(used),
        }
        for row, velocity, used in zip(
            final_records, residual_velocity, final_mask, strict=True
        )
    ]
    warning_codes: list[str] = []
    if final_mask.sum() < 500:
        warning_codes.append("THAR_LINE_COUNT_LOW")
    if rms_m_s > 150.0:
        warning_codes.append("WAVELENGTH_RMS_EXCEEDS_TARGET")
    qc = {
        "wavelength_rms_m_s": rms_m_s,
        "identified_line_count": int(final_mask.sum()),
        "identified_order_count": len(used_orders),
        "per_order_rms_m_s": {str(key): value for key, value in per_order_rms.items()},
        "target_rms_m_s": 150.0,
        "warning_codes": warning_codes,
        "passed": rms_m_s <= 150.0,
    }
    solution = WavelengthSolution(
        coefficients=base_coefficients,
        residual_rms=per_order_rms,
        channel_coefficients=channel_coefficients,
        channel_residual_rms={role: per_order_rms.copy() for role in channel_coefficients},
        wavelength_type="AIR",
        unit="nm",
        config_version=spectra.config_version,
        provenance={
            "algorithm": "espadons_thar_global_2d_v2",
            "source_commit": _SOURCE_COMMIT,
            "line_list": _line_list_path().name,
            "bootstrap": {
                **_BOOTSTRAP_REFERENCE,
                "role": "line-identification-only",
                "fit_degree": 2,
                "coefficients_m_lambda_nm": _BOOTSTRAP_COEFFICIENTS.tolist(),
            },
            "polynomial_degree": degree,
            "qc": qc,
        },
    )
    return ESPaDOnSWavelengthCalibration(
        solution=solution,
        qc=qc,
        identified_lines=identified,
    )
