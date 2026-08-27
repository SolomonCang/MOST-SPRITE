from __future__ import annotations

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
    intensity_product_ids: tuple[str, str, str, str]
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
    sign = float(group.reference_sign)
    provenance = {
        "adapter": "tests.adapters.espadons.adapt_reference_sign",
        "source_instrument": "ESPaDOnS",
        "source_product_id": group.polarization_product_id,
        "stokes": stokes,
        "sign_multiplier": group.reference_sign,
        "production_mapping_affected": False,
    }
    return polarization * sign, null1 * sign, null2 * sign, provenance


def group_for_product(product_id: str) -> ESPaDOnSGroup:
    for group in GROUPS.values():
        if product_id in {
            *group.raw_product_ids,
            *group.intensity_product_ids,
            group.polarization_product_id,
        }:
            return group
    raise KeyError(product_id)


def read_intensity_reference(path: Path, *, normalized: bool = True) -> IntensityReference:
    """Read the documented six-row Libre-ESpRIT intensity layout used only by tests."""
    with fits.open(path, memmap=False) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float64)
        product_id = str(hdul[0].header["FILENAME"])
    if data.ndim != 2 or data.shape[0] != 12:
        raise ValueError("unexpected ESPaDOnS intensity reference layout")
    row = 0 if normalized else 3
    return IntensityReference(
        wavelength_nm=data[row].copy(),
        intensity=data[row + 1].copy(),
        uncertainty=data[row + 2].copy(),
        normalized=normalized,
        velocity_corrected=True,
        provenance={
            "adapter": "tests.adapters.espadons.read_intensity_reference",
            "source_product_id": product_id,
            "row_layout": [row, row + 1, row + 2],
            "production_mapping_affected": False,
        },
    )


def read_polarization_reference(path: Path, *, normalized: bool = True) -> PolarizationReference:
    """Read I/P/N1/N2 and apply the explicit CFHT Q/U/V sign convention."""
    with fits.open(path, memmap=False) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float64)
        header = hdul[0].header
        product_id = str(header["FILENAME"])
        comments = str(header.get("COMMENT", ""))
    if data.ndim != 2 or data.shape[0] != 24:
        raise ValueError("unexpected ESPaDOnS polarization reference layout")
    group = group_for_product(product_id)
    row = 0 if normalized else 6
    polarization, null1, null2, sign_provenance = adapt_reference_sign(
        group.stokes,
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
            "velocity_corrected": True,
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
