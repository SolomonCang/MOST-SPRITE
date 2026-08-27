from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from most_sprite.domain.enums import DQBit


@dataclass(slots=True)
class NonPolarProduct:
    wavelength: NDArray[np.float64]
    target: NDArray[np.float64]
    sky: NDArray[np.float64]
    alpha: NDArray[np.float64]
    intensity: NDArray[np.float64]
    err_target: NDArray[np.float64]
    err_sky: NDArray[np.float64]
    err_alpha: NDArray[np.float64]
    err_intensity: NDArray[np.float64]
    dq: NDArray[np.uint32]
    background_subtracted: bool
    flux_unit: str = "electron"
    wavelength_unit: str = "nm"
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)


def subtract_sky(
    wavelength: NDArray[np.float64],
    target: NDArray[np.float64],
    sky: NDArray[np.float64] | None,
    alpha: NDArray[np.float64],
    target_variance: NDArray[np.float64],
    sky_variance: NDArray[np.float64] | None,
    alpha_variance: NDArray[np.float64],
    dq: NDArray[np.uint32] | None = None,
    *,
    flux_unit: str = "electron",
    wavelength_unit: str = "nm",
    config_version: str = "UNVERIFIED",
    provenance: dict[str, Any] | None = None,
) -> NonPolarProduct:
    quality = np.zeros(target.shape, dtype=np.uint32) if dq is None else dq.copy()
    sky_valid = (
        sky is not None
        and sky_variance is not None
        and np.all(np.isfinite(sky))
        and np.all(np.isfinite(sky_variance))
    )
    if sky_valid:
        assert sky is not None and sky_variance is not None
        intensity = target - alpha * sky
        intensity_variance = target_variance + alpha**2 * sky_variance + sky**2 * alpha_variance
        sky_output = sky
        sky_error = np.sqrt(sky_variance)
    else:
        intensity = target.copy()
        intensity_variance = target_variance.copy()
        sky_output = np.full(target.shape, np.nan)
        sky_error = np.full(target.shape, np.nan)
        quality |= DQBit.SKY_INVALID
    return NonPolarProduct(
        wavelength=wavelength.copy(),
        target=target.copy(),
        sky=sky_output,
        alpha=alpha.copy(),
        intensity=intensity,
        err_target=np.sqrt(target_variance),
        err_sky=sky_error,
        err_alpha=np.sqrt(alpha_variance),
        err_intensity=np.sqrt(intensity_variance),
        dq=quality,
        background_subtracted=bool(sky_valid),
        flux_unit=flux_unit,
        wavelength_unit=wavelength_unit,
        config_version=config_version,
        provenance={
            **(provenance or {}),
            "algorithm": "target-minus-alpha-sky-v1",
            "sky_valid": bool(sky_valid),
        },
    )
