from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class ESPaDOnSGroup:
    stokes: str
    raw_product_ids: tuple[str, str, str, str]
    intensity_product_ids: tuple[str, ...]
    polarization_product_id: str
    reference_sign: int


GROUPS: dict[str, ESPaDOnSGroup] = {
    "Q": ESPaDOnSGroup(
        stokes="Q",
        raw_product_ids=("1894880o", "1894881o", "1894882o", "1894883o"),
        intensity_product_ids=("1894880i", "1894881i", "1894882i", "1894883i"),
        polarization_product_id="1894880p",
        reference_sign=1,
    ),
    "U": ESPaDOnSGroup(
        stokes="U",
        raw_product_ids=("1894884o", "1894885o", "1894886o", "1894887o"),
        intensity_product_ids=("1894884i", "1894885i", "1894886i", "1894887i"),
        polarization_product_id="1894884p",
        reference_sign=-1,
    ),
    "V": ESPaDOnSGroup(
        stokes="V",
        raw_product_ids=("1894876o", "1894877o", "1894878o", "1894879o"),
        intensity_product_ids=("1894876i", "1894877i", "1894878i", "1894879i"),
        polarization_product_id="1894876p",
        reference_sign=1,
    ),
}


STANDARD_GROUPS: dict[str, ESPaDOnSGroup] = {
    "HR_5501_V": ESPaDOnSGroup(
        stokes="V",
        raw_product_ids=("3210588o", "3210589o", "3210590o", "3210591o"),
        intensity_product_ids=(),
        polarization_product_id="3210588p",
        reference_sign=1,
    ),
    "HD_236928_Q": ESPaDOnSGroup(
        stokes="Q",
        raw_product_ids=("3251968o", "3251969o", "3251970o", "3251971o"),
        intensity_product_ids=(),
        polarization_product_id="3251968p",
        reference_sign=1,
    ),
    "HD_236928_U": ESPaDOnSGroup(
        stokes="U",
        raw_product_ids=("3251972o", "3251973o", "3251974o", "3251975o"),
        intensity_product_ids=(),
        polarization_product_id="3251972p",
        reference_sign=-1,
    ),
}

ALL_GROUPS: tuple[ESPaDOnSGroup, ...] = (
    *GROUPS.values(),
    *STANDARD_GROUPS.values(),
)


@dataclass(frozen=True, slots=True)
class IntensityReference:
    wavelength_nm: NDArray[np.float64]
    intensity: NDArray[np.float64]
    uncertainty: NDArray[np.float64]
    normalized: bool
    velocity_corrected: bool
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PolarizationReference:
    wavelength_nm: NDArray[np.float64]
    intensity: NDArray[np.float64]
    polarization: NDArray[np.float64]
    null1: NDArray[np.float64]
    null2: NDArray[np.float64]
    uncertainty: NDArray[np.float64]
    provenance: dict[str, Any]


def adapt_reference_sign(
    stokes: str,
    polarization: NDArray[np.float64],
    null1: NDArray[np.float64],
    null2: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], dict[str, Any]]:
    """Convert the ESPaDOnS reference convention into the SPRITE test convention."""
    group = GROUPS[stokes]
    return adapt_reference_group_sign(group, polarization, null1, null2)


def adapt_reference_group_sign(
    group: ESPaDOnSGroup,
    polarization: NDArray[np.float64],
    null1: NDArray[np.float64],
    null2: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], dict[str, Any]]:
    """Apply the frozen sign convention for one explicit archive sequence."""
    sign = float(group.reference_sign)
    provenance = {
        "adapter": "tests.adapters.espadons.adapt_reference_group_sign",
        "source_instrument": "ESPaDOnS",
        "source_product_id": group.polarization_product_id,
        "stokes": group.stokes,
        "sign_multiplier": group.reference_sign,
        "production_mapping_affected": False,
    }
    return polarization * sign, null1 * sign, null2 * sign, provenance


def group_for_product(product_id: str) -> ESPaDOnSGroup:
    for group in ALL_GROUPS:
        if product_id in {
            *group.raw_product_ids,
            *group.intensity_product_ids,
            group.polarization_product_id,
        }:
            return group
    raise KeyError(product_id)


def read_intensity_reference(
    path: Path,
    *,
    normalized: bool = True,
    velocity_corrected: bool = True,
) -> IntensityReference:
    """Read the documented six-row Libre-ESpRIT intensity layout used only by tests."""
    with fits.open(path, memmap=False) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float64)
        header = hdul[0].header
        product_id = str(header["FILENAME"])
        comments = [str(value) for value in header.get("COMMENT", [])]
    if data.ndim != 2 or data.shape[0] != 12:
        raise ValueError("unexpected ESPaDOnS intensity reference layout")
    row = (0 if normalized else 3) + (0 if velocity_corrected else 6)
    velocity_matches = [
        match
        for comment in comments
        if (
            match := re.search(
                r"Heliocentric velocity of observer towards star\s*:\s*"
                r"([+-]?[0-9.]+)\s*km/s",
                comment,
            )
        )
    ]
    if not velocity_matches:
        raise ValueError("intensity reference omits heliocentric velocity provenance")
    heliocentric_velocity_km_s = float(velocity_matches[0].group(1))
    return IntensityReference(
        wavelength_nm=data[row].copy(),
        intensity=data[row + 1].copy(),
        uncertainty=data[row + 2].copy(),
        normalized=normalized,
        velocity_corrected=velocity_corrected,
        provenance={
            "adapter": "tests.adapters.espadons.read_intensity_reference",
            "source_product_id": product_id,
            "row_layout": [row, row + 1, row + 2],
            "heliocentric_velocity_km_s": heliocentric_velocity_km_s,
            "production_mapping_affected": False,
        },
    )


def reference_order_boundaries(
    wavelength_nm: NDArray[np.float64],
) -> NDArray[np.int64]:
    source_wave = np.asarray(wavelength_nm, dtype=np.float64)
    steps = np.diff(source_wave)
    return np.concatenate(
        (
            np.array([0], dtype=np.int64),
            np.flatnonzero((steps < 0) | (steps > 0.1)) + 1,
            np.array([source_wave.size], dtype=np.int64),
        )
    )


def split_intensity_reference_orders(
    reference: IntensityReference,
) -> dict[int, IntensityReference]:
    """Split the CFHT concatenation and label physical orders m=61..22."""
    boundaries = reference_order_boundaries(reference.wavelength_nm)
    if boundaries.size - 1 != 40:
        raise ValueError(
            "expected forty ESPaDOnS intensity reference orders, found "
            f"{boundaries.size - 1}"
        )
    result: dict[int, IntensityReference] = {}
    for index, (start, stop) in enumerate(
        zip(boundaries[:-1], boundaries[1:], strict=True)
    ):
        order = 61 - index
        result[order] = IntensityReference(
            wavelength_nm=reference.wavelength_nm[start:stop].copy(),
            intensity=reference.intensity[start:stop].copy(),
            uncertainty=reference.uncertainty[start:stop].copy(),
            normalized=reference.normalized,
            velocity_corrected=reference.velocity_corrected,
            provenance={
                **reference.provenance,
                "physical_order": order,
                "comparison_order_split": "cfht-concatenated-m61-to-m22-v1",
            },
        )
    return result


def read_polarization_reference(
    path: Path,
    *,
    normalized: bool = True,
    velocity_corrected: bool = True,
) -> PolarizationReference:
    """Read I/P/N1/N2 and apply the explicit CFHT Q/U/V sign convention."""
    with fits.open(path, memmap=False) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float64)
        header = hdul[0].header
        product_id = str(header["FILENAME"])
        comments = str(header.get("COMMENT", ""))
    if data.ndim != 2 or data.shape[0] != 24:
        raise ValueError("unexpected ESPaDOnS polarization reference layout")
    group = group_for_product(product_id)
    row = (0 if normalized else 6) + (0 if velocity_corrected else 12)
    polarization, null1, null2, sign_provenance = adapt_reference_group_sign(
        group,
        data[row + 2],
        data[row + 3],
        data[row + 4],
    )
    missing_sources = [value for value in group.raw_product_ids if value not in comments]
    if missing_sources:
        raise ValueError(f"reference header omits source files: {missing_sources}")
    return PolarizationReference(
        wavelength_nm=data[row].copy(),
        intensity=data[row + 1].copy(),
        polarization=polarization.copy(),
        null1=null1.copy(),
        null2=null2.copy(),
        uncertainty=data[row + 5].copy(),
        provenance={
            **sign_provenance,
            "adapter": "tests.adapters.espadons.read_polarization_reference",
            "row_layout": [row, row + 1, row + 2, row + 3, row + 4, row + 5],
            "source_raw_product_ids": list(group.raw_product_ids),
            "normalized": normalized,
            "velocity_corrected": velocity_corrected,
        },
    )


def wavelength_resolution_offsets(
    candidate_nm: NDArray[np.float64],
    reference_nm: NDArray[np.float64],
    *,
    resolving_power: float = 65_000.0,
) -> NDArray[np.float64]:
    scale = reference_nm / resolving_power
    return np.divide(
        np.abs(candidate_nm - reference_nm),
        scale,
        out=np.full(reference_nm.shape, np.inf),
        where=np.isfinite(scale) & (scale > 0),
    )


def robust_continuum_rms(
    candidate: NDArray[np.float64],
    reference: NDArray[np.float64],
    mask: NDArray[np.bool_],
) -> float:
    valid = mask & np.isfinite(candidate) & np.isfinite(reference) & (reference != 0)
    residual = candidate[valid] / reference[valid] - 1.0
    if residual.size == 0:
        return float("inf")
    center = np.median(residual)
    mad = np.median(np.abs(residual - center))
    keep = np.abs(residual - center) <= max(5.0 * 1.4826 * mad, 1e-12)
    return float(np.sqrt(np.mean(residual[keep] ** 2)))


def normalized_residual_quantiles(
    candidate: NDArray[np.float64],
    reference: NDArray[np.float64],
    reference_uncertainty: NDArray[np.float64],
    mask: NDArray[np.bool_],
) -> tuple[float, float]:
    valid = (
        mask
        & np.isfinite(candidate)
        & np.isfinite(reference)
        & np.isfinite(reference_uncertainty)
        & (reference_uncertainty > 0)
    )
    residual = np.abs(candidate[valid] - reference[valid]) / reference_uncertainty[valid]
    if residual.size == 0:
        return float("inf"), float("inf")
    return float(np.median(residual)), float(np.quantile(residual, 0.99))


def merge_polarization_reference(
    reference: PolarizationReference,
    wavelength_nm: NDArray[np.float64],
) -> PolarizationReference:
    """Merge the archive's concatenated native orders onto a comparison grid.

    The CFHT ``p`` products concatenate overlapping echelle orders and reset
    wavelength at every order boundary.  Treating that vector as globally
    monotonic silently mixes unrelated orders, so the regression adapter must
    resample each order independently before inverse-variance combination.
    This helper is test-only and never feeds a production science product.
    """
    source_wave = np.asarray(reference.wavelength_nm, dtype=np.float64)
    boundaries = reference_order_boundaries(source_wave)
    fields = (
        reference.intensity,
        reference.polarization,
        reference.null1,
        reference.null2,
    )
    weighted = [np.zeros(wavelength_nm.shape, dtype=np.float64) for _ in fields]
    weight_sum = np.zeros(wavelength_nm.shape, dtype=np.float64)
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        order_wave = source_wave[start:stop]
        order_sigma = reference.uncertainty[start:stop]
        valid = np.isfinite(order_wave) & np.isfinite(order_sigma) & (order_sigma > 0)
        if np.count_nonzero(valid) < 2:
            continue
        order_wave = order_wave[valid]
        order_sigma = order_sigma[valid]
        inside = (wavelength_nm >= order_wave[0]) & (wavelength_nm <= order_wave[-1])
        if not np.any(inside):
            continue
        target = wavelength_nm[inside]
        interpolated_sigma = np.interp(target, order_wave, order_sigma)
        weights = 1.0 / np.square(interpolated_sigma)
        weight_sum[inside] += weights
        for accumulator, values in zip(weighted, fields, strict=True):
            order_values = np.asarray(values[start:stop], dtype=np.float64)[valid]
            accumulator[inside] += np.interp(target, order_wave, order_values) * weights

    merged = [
        np.divide(
            accumulator,
            weight_sum,
            out=np.full(wavelength_nm.shape, np.nan, dtype=np.float64),
            where=weight_sum > 0,
        )
        for accumulator in weighted
    ]
    uncertainty = np.divide(
        1.0,
        np.sqrt(weight_sum),
        out=np.full(wavelength_nm.shape, np.inf, dtype=np.float64),
        where=weight_sum > 0,
    )
    return PolarizationReference(
        wavelength_nm=np.asarray(wavelength_nm, dtype=np.float64).copy(),
        intensity=merged[0],
        polarization=merged[1],
        null1=merged[2],
        null2=merged[3],
        uncertainty=uncertainty,
        provenance={
            **reference.provenance,
            "comparison_order_merge": "per-order-linear-inverse-variance-v1",
            "production_mapping_affected": False,
        },
    )


def match_spectral_line_continuum(
    wavelength_nm: NDArray[np.float64],
    candidate: NDArray[np.float64],
    reference: NDArray[np.float64],
    mask: NDArray[np.bool_],
    *,
    bin_width_nm: float = 0.5,
) -> NDArray[np.float64]:
    """Remove only the smooth candidate-reference offset for line regression.

    ESPaDOnS does not provide reliable absolute continuum polarization and the
    archived Libre-ESpRIT product removes it, while SPRITE deliberately retains
    the measured ratio.  A binned median of their difference therefore defines
    a comparison-only baseline without altering either published product.
    """
    valid = (
        np.asarray(mask, dtype=bool)
        & np.isfinite(wavelength_nm)
        & np.isfinite(candidate)
        & np.isfinite(reference)
    )
    if np.count_nonzero(valid) < 2:
        return np.full(candidate.shape, np.nan, dtype=np.float64)
    lower = np.floor(np.min(wavelength_nm[valid]) / bin_width_nm) * bin_width_nm
    upper = np.ceil(np.max(wavelength_nm[valid]) / bin_width_nm) * bin_width_nm
    centers = np.arange(lower + bin_width_nm / 2.0, upper, bin_width_nm)
    indices = np.floor((wavelength_nm - lower) / bin_width_nm).astype(np.int64)
    difference = np.asarray(candidate, dtype=np.float64) - np.asarray(reference, dtype=np.float64)
    medians = np.full(centers.shape, np.nan, dtype=np.float64)
    for index in range(centers.size):
        selected = difference[valid & (indices == index)]
        if selected.size:
            medians[index] = np.median(selected)
    populated = np.isfinite(medians)
    if np.count_nonzero(populated) < 2:
        return np.full(candidate.shape, np.nan, dtype=np.float64)
    baseline = np.interp(
        wavelength_nm,
        centers[populated],
        medians[populated],
    )
    return np.asarray(candidate, dtype=np.float64) - baseline
