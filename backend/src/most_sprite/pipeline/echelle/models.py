"""SPRITE-native echelle domain models.

Algorithm lineage: GAMSE commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9.
This file is a MOST-SPRITE rewrite and does not expose or import GAMSE types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
UIntArray = NDArray[np.uint32]


@dataclass(slots=True)
class CalibrationFrame:
    data: FloatArray
    variance: FloatArray
    dq: UIntArray
    unit: str = "adu"
    coordinates: dict[str, FloatArray] = field(default_factory=dict)
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TraceModel:
    order_ids: NDArray[np.int32]
    coefficients: FloatArray
    widths: FloatArray
    dispersion_axis: int = 1
    unit: str = "pixel"
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)

    def centers(self, pixels: FloatArray) -> FloatArray:
        return np.vstack([np.polyval(coefficients, pixels) for coefficients in self.coefficients])


@dataclass(slots=True)
class FlatModel:
    response: FloatArray
    blaze: FloatArray
    variance: FloatArray
    dq: UIntArray
    unit: str = "dimensionless"
    coordinates: dict[str, FloatArray] = field(default_factory=dict)
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SpectrumChannel:
    role: str
    order: NDArray[np.int32]
    pixel: FloatArray
    wavelength: FloatArray
    flux: FloatArray
    variance: FloatArray
    dq: UIntArray
    covariance_lag1: FloatArray | None = None
    unit: str = "electron"
    wavelength_unit: str = "nm"
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SpectrumSet:
    channels: dict[str, SpectrumChannel]
    native_grid: bool = True
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WavelengthSolution:
    coefficients: dict[int, FloatArray]
    residual_rms: dict[int, float]
    channel_coefficients: dict[str, dict[int, FloatArray]] = field(default_factory=dict)
    channel_residual_rms: dict[str, dict[int, float]] = field(default_factory=dict)
    wavelength_type: str = "UNVERIFIED"
    unit: str = "nm"
    config_version: str = "UNVERIFIED"
    provenance: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, order: int, pixels: FloatArray, *, role: str | None = None) -> FloatArray:
        coefficients = self.coefficients
        if role is not None and role in self.channel_coefficients:
            coefficients = self.channel_coefficients[role]
        return np.asarray(np.polyval(coefficients[order], pixels), dtype=np.float64)
