from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from most_sprite.configuration import SIGN_VECTORS
from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.instruments.base import DemodulationModel


@dataclass(slots=True)
class BeamSpectrum:
    wavelength: NDArray[np.float64]
    o_flux: NDArray[np.float64]
    e_flux: NDArray[np.float64]
    o_variance: NDArray[np.float64]
    e_variance: NDArray[np.float64]
    dq: NDArray[np.uint32]
    sub_index: int
    o_covariance_lag1: NDArray[np.float64] | None = None
    e_covariance_lag1: NDArray[np.float64] | None = None
    exposure_id: str = ""
    flux_unit: str = "electron"
    wavelength_unit: str = "nm"
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolarimetricProduct:
    wavelength: NDArray[np.float64]
    intensity: NDArray[np.float64]
    polarization: NDArray[np.float64]
    null1: NDArray[np.float64]
    null2: NDArray[np.float64]
    err_intensity: NDArray[np.float64]
    err_polarization: NDArray[np.float64]
    err_null1: NDArray[np.float64]
    err_null2: NDArray[np.float64]
    covariance_p_null1: NDArray[np.float64]
    covariance_p_null2: NDArray[np.float64]
    covariance_null1_null2: NDArray[np.float64]
    dq: NDArray[np.uint32]
    difference_check: NDArray[np.float64]
    covariance_lag1_intensity: NDArray[np.float64] | None = None
    covariance_lag1_polarization: NDArray[np.float64] | None = None
    covariance_lag1_null1: NDArray[np.float64] | None = None
    covariance_lag1_null2: NDArray[np.float64] | None = None
    intensity_unit: str = "electron"
    polarization_unit: str = "dimensionless"
    wavelength_unit: str = "nm"
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)
    qc: dict[str, Any] = field(default_factory=dict)


def _combination(
    log_ratios: NDArray[np.float64],
    variances: NDArray[np.float64],
    signs: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    y = np.sum(signs[:, None] * log_ratios, axis=0) / 4.0
    var_y = np.sum((signs[:, None] ** 2) * variances, axis=0) / 16.0
    result = np.tanh(y / 2.0)
    derivative = 0.5 * (1.0 - result**2)
    variance = derivative**2 * var_y
    return result, variance


def demodulate_group(
    exposures: list[BeamSpectrum],
    *,
    model: DemodulationModel | None = None,
    null_sigma_threshold: float = 5.0,
) -> PolarimetricProduct:
    if len(exposures) != 4:
        raise ValueError("a formal polarimetric product requires exactly four subexposures")
    if {item.sub_index for item in exposures} != {1, 2, 3, 4}:
        raise ValueError("subexposures must have unique indices 1, 2, 3 and 4")
    exposures = sorted(exposures, key=lambda item: item.sub_index)
    config_versions = {item.config_version for item in exposures}
    if len(config_versions) != 1:
        raise ValueError("all subexposures must use the same configuration version")
    reference_wave = exposures[0].wavelength
    if any(not np.array_equal(item.wavelength, reference_wave) for item in exposures[1:]):
        raise ValueError("all subexposures must be on the same controlled wavelength grid")
    o_flux = np.stack([item.o_flux for item in exposures])
    e_flux = np.stack([item.e_flux for item in exposures])
    o_variance = np.stack([item.o_variance for item in exposures])
    e_variance = np.stack([item.e_variance for item in exposures])
    invalid = (o_flux <= 0) | (e_flux <= 0) | ~np.isfinite(o_flux) | ~np.isfinite(e_flux)
    safe_o = np.where(invalid, np.nan, o_flux)
    safe_e = np.where(invalid, np.nan, e_flux)
    log_ratios = np.log(safe_o) - np.log(safe_e)
    log_variance = o_variance / safe_o**2 + e_variance / safe_e**2

    vectors = (
        {
            "science": list(model.science_signs),
            "null1": list(model.null1_signs),
            "null2": list(model.null2_signs),
        }
        if model is not None
        else SIGN_VECTORS
    )
    output_sign = model.output_sign if model is not None else 1.0
    science_signs = output_sign * np.asarray(vectors["science"], dtype=np.float64)
    null1_signs = np.asarray(vectors["null1"], dtype=np.float64)
    null2_signs = np.asarray(vectors["null2"], dtype=np.float64)
    science, science_var = _combination(log_ratios, log_variance, science_signs)
    null1, null1_var = _combination(
        log_ratios, log_variance, null1_signs
    )
    null2, null2_var = _combination(
        log_ratios, log_variance, null2_signs
    )
    beam_intensity = o_flux + e_flux
    valid_intensity = np.all(np.isfinite(beam_intensity), axis=0)
    intensity = np.divide(
        np.sum(np.where(np.isfinite(beam_intensity), beam_intensity, 0.0), axis=0),
        4.0,
        out=np.full(reference_wave.shape, np.nan),
        where=valid_intensity,
    )
    intensity_var = np.divide(
        np.sum(
            np.where(
                np.isfinite(o_variance + e_variance),
                o_variance + e_variance,
                0.0,
            ),
            axis=0,
        ),
        16.0,
        out=np.full(reference_wave.shape, np.inf),
        where=valid_intensity,
    )
    differences = (safe_o - safe_e) / (safe_o + safe_e)
    difference_check = (
        np.nansum(science_signs[:, None] * differences, axis=0) / 4.0
    )
    dq = np.bitwise_or.reduce(np.stack([item.dq for item in exposures]), axis=0)
    dq[np.any(invalid, axis=0)] |= DQBit.EXTRACTION_FAILED
    err_n1 = np.sqrt(null1_var)
    err_n2 = np.sqrt(null2_var)
    z1 = np.divide(null1, err_n1, out=np.zeros_like(null1), where=err_n1 > 0)
    z2 = np.divide(null2, err_n2, out=np.zeros_like(null2), where=err_n2 > 0)
    if np.nanmax(np.abs(z1), initial=0.0) > null_sigma_threshold:
        dq[np.abs(z1) > null_sigma_threshold] |= DQBit.NULL1_EXCESS
    if np.nanmax(np.abs(z2), initial=0.0) > null_sigma_threshold:
        dq[np.abs(z2) > null_sigma_threshold] |= DQBit.NULL2_EXCESS
    derivative_science = 0.5 * (1.0 - science**2)
    derivative_null1 = 0.5 * (1.0 - null1**2)
    derivative_null2 = 0.5 * (1.0 - null2**2)

    def stacked_lag(name: str) -> NDArray[np.float64]:
        values = [getattr(item, name) for item in exposures]
        return np.stack(
            [
                np.zeros(reference_wave.shape, dtype=np.float64)
                if value is None
                else value
                for value in values
            ]
        )

    o_lag = stacked_lag("o_covariance_lag1")
    e_lag = stacked_lag("e_covariance_lag1")
    next_o = np.roll(safe_o, -1, axis=1)
    next_e = np.roll(safe_e, -1, axis=1)
    log_lag = np.divide(
        o_lag,
        safe_o * next_o,
        out=np.zeros_like(o_lag),
        where=np.isfinite(safe_o * next_o) & (safe_o * next_o != 0),
    ) + np.divide(
        e_lag,
        safe_e * next_e,
        out=np.zeros_like(e_lag),
        where=np.isfinite(safe_e * next_e) & (safe_e * next_e != 0),
    )
    log_lag[:, -1] = 0.0

    def transformed_lag(
        signs: NDArray[np.float64], derivative: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        covariance = np.sum((signs[:, None] ** 2) * log_lag, axis=0) / 16.0
        next_derivative = np.roll(derivative, -1)
        result = derivative * next_derivative * covariance
        result[-1] = 0.0
        return result

    def transformed_covariance(
        first_signs: NDArray[np.float64],
        second_signs: NDArray[np.float64],
        first_derivative: NDArray[np.float64],
        second_derivative: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        log_covariance = (
            np.sum(
                first_signs[:, None] * second_signs[:, None] * log_variance,
                axis=0,
            )
            / 16.0
        )
        return first_derivative * second_derivative * log_covariance

    def finite_summary(values: NDArray[np.float64]) -> tuple[float, float]:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return float("nan"), float("nan")
        return float(np.mean(finite)), float(np.sqrt(np.mean(finite**2)))

    null1_mean, null1_rms = finite_summary(null1)
    null2_mean, null2_rms = finite_summary(null2)
    finite_z1 = np.abs(z1[np.isfinite(z1)])
    finite_z2 = np.abs(z2[np.isfinite(z2)])

    def percentile(values: NDArray[np.float64], quantile: float) -> float:
        return float(np.percentile(values, quantile)) if values.size else float("nan")

    return PolarimetricProduct(
        wavelength=reference_wave.copy(),
        intensity=intensity,
        polarization=science,
        null1=null1,
        null2=null2,
        err_intensity=np.sqrt(intensity_var),
        err_polarization=np.sqrt(science_var),
        err_null1=err_n1,
        err_null2=err_n2,
        covariance_p_null1=transformed_covariance(
            science_signs,
            null1_signs,
            derivative_science,
            derivative_null1,
        ),
        covariance_p_null2=transformed_covariance(
            science_signs,
            null2_signs,
            derivative_science,
            derivative_null2,
        ),
        covariance_null1_null2=transformed_covariance(
            null1_signs,
            null2_signs,
            derivative_null1,
            derivative_null2,
        ),
        dq=dq,
        difference_check=difference_check,
        covariance_lag1_intensity=np.sum(o_lag + e_lag, axis=0) / 16.0,
        covariance_lag1_polarization=transformed_lag(
            science_signs, derivative_science
        ),
        covariance_lag1_null1=transformed_lag(null1_signs, derivative_null1),
        covariance_lag1_null2=transformed_lag(null2_signs, derivative_null2),
        intensity_unit=exposures[0].flux_unit,
        wavelength_unit=exposures[0].wavelength_unit,
        config_version=exposures[0].config_version,
        provenance={
            "algorithm": "ratio-log-v1",
            "exposure_ids": [item.exposure_id for item in exposures],
            "subexposure_order": [item.sub_index for item in exposures],
            "sign_vectors": vectors,
            "demodulation_model": model.version if model is not None else "most-v1",
            "output_sign": output_sign,
        },
        qc={
            "null1_mean": null1_mean,
            "null1_rms": null1_rms,
            "null2_mean": null2_mean,
            "null2_rms": null2_rms,
            "null1_max_sigma": (
                float(np.max(finite_z1)) if finite_z1.size else float("nan")
            ),
            "null2_max_sigma": (
                float(np.max(finite_z2)) if finite_z2.size else float("nan")
            ),
            "null1_p99_sigma": percentile(finite_z1, 99.0),
            "null2_p99_sigma": percentile(finite_z2, 99.0),
            "null1_excess_fraction": (
                float(np.mean(finite_z1 > null_sigma_threshold))
                if finite_z1.size
                else float("nan")
            ),
            "null2_excess_fraction": (
                float(np.mean(finite_z2 > null_sigma_threshold))
                if finite_z2.size
                else float("nan")
            ),
        },
    )
