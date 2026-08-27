"""Per-order ESPaDOnS demodulation and deterministic overlap merging."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from scipy.ndimage import median_filter

from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.echelle.models import SpectrumSet
from most_sprite.pipeline.instruments.base import DemodulationModel
from most_sprite.pipeline.polarimetry.demodulation import (
    BeamSpectrum,
    PolarimetricProduct,
    demodulate_group,
)


def demodulate_resampled_orders(
    spectra: list[SpectrumSet],
    *,
    sub_indices: list[int],
    exposure_ids: list[str],
    model: DemodulationModel,
    null_sigma_threshold: float,
) -> dict[int, PolarimetricProduct]:
    if len(spectra) != 4 or len(sub_indices) != 4 or len(exposure_ids) != 4:
        raise ValueError("four resampled ESPaDOnS exposures are required")
    reference = spectra[0].channels["O_BEAM"]
    orders = sorted(int(value) for value in np.unique(reference.order))
    result: dict[int, PolarimetricProduct] = {}
    for order in orders:
        beams: list[BeamSpectrum] = []
        for spectrum, sub_index, exposure_id in zip(
            spectra, sub_indices, exposure_ids, strict=True
        ):
            o_channel = spectrum.channels["O_BEAM"]
            e_channel = spectrum.channels["E_BEAM"]
            o_selection = o_channel.order == order
            e_selection = e_channel.order == order
            beams.append(
                BeamSpectrum(
                    wavelength=o_channel.wavelength[o_selection],
                    o_flux=o_channel.flux[o_selection],
                    e_flux=e_channel.flux[e_selection],
                    o_variance=o_channel.variance[o_selection],
                    e_variance=e_channel.variance[e_selection],
                    dq=np.bitwise_or(
                        o_channel.dq[o_selection], e_channel.dq[e_selection]
                    ),
                    sub_index=sub_index,
                    o_covariance_lag1=(
                        o_channel.covariance_lag1[o_selection]
                        if o_channel.covariance_lag1 is not None
                        else None
                    ),
                    e_covariance_lag1=(
                        e_channel.covariance_lag1[e_selection]
                        if e_channel.covariance_lag1 is not None
                        else None
                    ),
                    exposure_id=exposure_id,
                    flux_unit=o_channel.unit,
                    wavelength_unit=o_channel.wavelength_unit,
                    config_version=spectrum.config_version,
                    provenance=spectrum.provenance,
                )
            )
        result[order] = demodulate_group(
            beams, model=model, null_sigma_threshold=null_sigma_threshold
        )
    return result


def _blaze_on_grid(
    blaze: dict[str, dict[int, np.ndarray]], order: int, size: int
) -> np.ndarray:
    values = [
        np.asarray(blaze[role][order], dtype=np.float64)
        for role in ("O_BEAM", "E_BEAM")
        if role in blaze and order in blaze[role]
    ]
    if not values:
        return np.ones(size, dtype=np.float64)
    source = np.nanmean(values, axis=0)
    source = np.clip(source, 0.0, None)
    result = np.interp(
        np.linspace(0.0, 1.0, size),
        np.linspace(0.0, 1.0, source.size),
        source,
    )
    maximum = float(np.nanmax(result))
    return result / maximum if maximum > 0 else np.ones(size, dtype=np.float64)


def _weighted_merge(
    values: list[np.ndarray],
    variances: list[np.ndarray],
    blaze_weights: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    shape = values[0].shape
    numerator = np.zeros(shape, dtype=np.float64)
    denominator = np.zeros(shape, dtype=np.float64)
    weights: list[np.ndarray] = []
    for value, variance, blaze in zip(values, variances, blaze_weights, strict=True):
        valid = np.isfinite(value) & np.isfinite(variance) & (variance > 0)
        weight = np.zeros(shape, dtype=np.float64)
        weight[valid] = np.clip(blaze[valid], 0.0, None) / variance[valid]
        numerator[valid] += weight[valid] * value[valid]
        denominator[valid] += weight[valid]
        weights.append(weight)
    merged = np.divide(
        numerator,
        denominator,
        out=np.full(shape, np.nan, dtype=np.float64),
        where=denominator > 0,
    )
    variance = np.zeros(shape, dtype=np.float64)
    for weight, input_variance in zip(weights, variances, strict=True):
        variance += weight**2 * np.where(np.isfinite(input_variance), input_variance, 0.0)
    variance = np.divide(
        variance,
        denominator**2,
        out=np.full(shape, np.inf, dtype=np.float64),
        where=denominator > 0,
    )
    return merged, variance, weights


def merge_polarimetric_orders(
    products: dict[int, PolarimetricProduct],
    global_grid: np.ndarray,
    *,
    blaze: dict[str, dict[int, np.ndarray]],
) -> PolarimetricProduct:
    if not products:
        raise ValueError("at least one demodulated order is required")
    size = global_grid.size
    fields = {
        "intensity": ("intensity", "err_intensity"),
        "polarization": ("polarization", "err_polarization"),
        "null1": ("null1", "err_null1"),
        "null2": ("null2", "err_null2"),
        "difference_check": ("difference_check", "err_polarization"),
    }
    values_by_field: dict[str, list[np.ndarray]] = {name: [] for name in fields}
    variances_by_field: dict[str, list[np.ndarray]] = {name: [] for name in fields}
    blaze_by_order: list[np.ndarray] = []
    dq_inputs: list[np.ndarray] = []
    order_slices: list[tuple[int, int, PolarimetricProduct]] = []
    for order, product in sorted(products.items(), reverse=True):
        indices = np.searchsorted(global_grid, product.wavelength)
        valid_index = (
            (indices >= 0)
            & (indices < size)
            & np.isclose(global_grid[np.clip(indices, 0, size - 1)], product.wavelength)
        )
        if not valid_index.all():
            raise ValueError(f"order {order} is not a subset of the frozen L3 grid")
        start = int(indices[0])
        stop = int(indices[-1]) + 1
        order_slices.append((start, stop, product))
        blaze_full = np.zeros(size, dtype=np.float64)
        blaze_full[start:stop] = _blaze_on_grid(blaze, order, stop - start)
        blaze_by_order.append(blaze_full)
        dq_full = np.zeros(size, dtype=np.uint32)
        dq_full[start:stop] = product.dq
        dq_inputs.append(dq_full)
        for output_name, (value_name, error_name) in fields.items():
            value = np.full(size, np.nan, dtype=np.float64)
            variance = np.full(size, np.inf, dtype=np.float64)
            value[start:stop] = getattr(product, value_name)
            variance[start:stop] = getattr(product, error_name) ** 2
            values_by_field[output_name].append(value)
            variances_by_field[output_name].append(variance)
    merged: dict[str, np.ndarray] = {}
    merged_variance: dict[str, np.ndarray] = {}
    merged_weights: dict[str, list[np.ndarray]] = {}
    for name in fields:
        merged[name], merged_variance[name], merged_weights[name] = _weighted_merge(
            values_by_field[name], variances_by_field[name], blaze_by_order
        )
    dq = np.zeros(size, dtype=np.uint32)
    covered = np.zeros(size, dtype=bool)
    for item, values in zip(dq_inputs, values_by_field["intensity"], strict=True):
        selection = np.isfinite(values)
        dq[selection] |= item[selection]
        covered |= selection
    dq[~covered] |= DQBit.ORDER_GAP

    def merge_cross_covariance(name: str, first: str, second: str) -> np.ndarray:
        numerator = np.zeros(size, dtype=np.float64)
        first_total = np.sum(merged_weights[first], axis=0)
        second_total = np.sum(merged_weights[second], axis=0)
        for index, (_, _, product) in enumerate(order_slices):
            start, stop, _ = order_slices[index]
            covariance = np.zeros(size, dtype=np.float64)
            covariance[start:stop] = getattr(product, name)
            numerator += (
                merged_weights[first][index]
                * merged_weights[second][index]
                * covariance
            )
        return np.divide(
            numerator,
            first_total * second_total,
            out=np.zeros(size, dtype=np.float64),
            where=(first_total > 0) & (second_total > 0),
        )

    def merge_lag(name: str, field: str) -> np.ndarray:
        numerator = np.zeros(size, dtype=np.float64)
        total = np.sum(merged_weights[field], axis=0)
        for index, (start, stop, product) in enumerate(order_slices):
            source = getattr(product, name)
            if source is None:
                continue
            lag = np.zeros(size, dtype=np.float64)
            lag[start:stop] = np.nan_to_num(source, nan=0.0, posinf=0.0, neginf=0.0)
            weight = merged_weights[field][index]
            numerator[:-1] += weight[:-1] * weight[1:] * lag[:-1]
        result = np.divide(
            numerator,
            total * np.roll(total, -1),
            out=np.zeros(size, dtype=np.float64),
            where=(total > 0) & (np.roll(total, -1) > 0),
        )
        result[-1] = 0.0
        return result

    reference = next(iter(products.values()))
    err_n1 = np.sqrt(merged_variance["null1"])
    err_n2 = np.sqrt(merged_variance["null2"])
    z1 = np.divide(merged["null1"], err_n1, out=np.zeros(size), where=err_n1 > 0)
    z2 = np.divide(merged["null2"], err_n2, out=np.zeros(size), where=err_n2 > 0)
    def finite_summary(values: np.ndarray) -> tuple[float, float]:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return float("nan"), float("nan")
        return float(np.mean(finite)), float(np.sqrt(np.mean(finite**2)))

    null1_mean, null1_rms = finite_summary(merged["null1"])
    null2_mean, null2_rms = finite_summary(merged["null2"])
    finite_z1 = np.abs(z1[np.isfinite(z1)])
    finite_z2 = np.abs(z2[np.isfinite(z2)])

    def percentile(values: np.ndarray, quantile: float) -> float:
        return float(np.percentile(values, quantile)) if values.size else float("nan")

    qc = {
        "null1_mean": null1_mean,
        "null1_rms": null1_rms,
        "null2_mean": null2_mean,
        "null2_rms": null2_rms,
        "null1_max_sigma": float(np.nanmax(np.abs(z1), initial=0.0)),
        "null2_max_sigma": float(np.nanmax(np.abs(z2), initial=0.0)),
        "null1_p99_sigma": percentile(finite_z1, 99.0),
        "null2_p99_sigma": percentile(finite_z2, 99.0),
        "null1_excess_fraction": (
            float(np.mean(finite_z1 > 5.0)) if finite_z1.size else float("nan")
        ),
        "null2_excess_fraction": (
            float(np.mean(finite_z2 > 5.0)) if finite_z2.size else float("nan")
        ),
        "merged_order_count": len(products),
        "gap_pixel_count": int((~covered).sum()),
        "valid_polarization_fraction": float(
            np.mean(np.isfinite(merged["polarization"]))
        ),
    }
    return PolarimetricProduct(
        wavelength=np.asarray(global_grid, dtype=np.float64),
        intensity=merged["intensity"],
        polarization=merged["polarization"],
        null1=merged["null1"],
        null2=merged["null2"],
        err_intensity=np.sqrt(merged_variance["intensity"]),
        err_polarization=np.sqrt(merged_variance["polarization"]),
        err_null1=err_n1,
        err_null2=err_n2,
        covariance_p_null1=merge_cross_covariance(
            "covariance_p_null1", "polarization", "null1"
        ),
        covariance_p_null2=merge_cross_covariance(
            "covariance_p_null2", "polarization", "null2"
        ),
        covariance_null1_null2=merge_cross_covariance(
            "covariance_null1_null2", "null1", "null2"
        ),
        dq=dq,
        difference_check=merged["difference_check"],
        covariance_lag1_intensity=merge_lag(
            "covariance_lag1_intensity", "intensity"
        ),
        covariance_lag1_polarization=merge_lag(
            "covariance_lag1_polarization", "polarization"
        ),
        covariance_lag1_null1=merge_lag("covariance_lag1_null1", "null1"),
        covariance_lag1_null2=merge_lag("covariance_lag1_null2", "null2"),
        intensity_unit=reference.intensity_unit,
        polarization_unit=reference.polarization_unit,
        wavelength_unit=reference.wavelength_unit,
        config_version=reference.config_version,
        provenance={
            **reference.provenance,
            "order_merge": "inverse-variance-times-blaze-v1",
            "order_ids": sorted(products, reverse=True),
            "common_grid_velocity_km_s": 1.8,
            "common_grid_resampling_count": 1,
        },
        qc=qc,
    )


def normalize_stokes_intensity(product: PolarimetricProduct) -> PolarimetricProduct:
    intensity = np.asarray(product.intensity, dtype=np.float64)
    valid = np.isfinite(intensity) & (intensity > 0)
    fill = float(np.nanmedian(intensity[valid])) if valid.any() else 1.0
    working = np.where(valid, intensity, fill)
    continuum = median_filter(working, 1001, mode="nearest")
    good = np.isfinite(continuum) & (continuum > 0)
    normalized = np.divide(
        intensity,
        continuum,
        out=np.full(intensity.shape, np.nan),
        where=good,
    )
    error = np.divide(
        product.err_intensity,
        continuum,
        out=np.full(intensity.shape, np.inf),
        where=good,
    )
    dq = product.dq.copy()
    dq[~good] |= DQBit.NORMALIZATION_FAILED
    lag = product.covariance_lag1_intensity
    if lag is not None:
        next_continuum = np.roll(continuum, -1)
        lag = np.divide(
            lag,
            continuum * next_continuum,
            out=np.zeros(lag.shape),
            where=good & np.roll(good, -1),
        )
    return replace(
        product,
        intensity=normalized,
        err_intensity=error,
        dq=dq,
        covariance_lag1_intensity=lag,
        intensity_unit="continuum-normalized",
        provenance={
            **product.provenance,
            "normalization": "robust-median-I-only-v1",
            "polarization_continuum_removed": False,
        },
    )


def shift_wavelength_coordinate(
    product: PolarimetricProduct,
    *,
    velocity_m_s: float,
    frame: str,
    provenance: dict[str, Any] | None = None,
) -> PolarimetricProduct:
    factor = 1.0 + velocity_m_s / 299_792_458.0
    return replace(
        product,
        wavelength=product.wavelength * factor,
        provenance={
            **product.provenance,
            "coordinate_frame": frame,
            "coordinate_velocity_m_s": velocity_m_s,
            "coordinate_only_no_resampling": True,
            **(provenance or {}),
        },
    )
