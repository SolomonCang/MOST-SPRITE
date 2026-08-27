"""Wavelength fitting rewritten from audited GAMSE global-fit responsibilities.

Upstream: gamse/echelle/wlcalib.py at commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9
Upstream SHA-256: a4fa6a28d5091dd43b1d5c2aaee11d4d431cb13cef0a178a7c2e3766d28fbd9b
Modified for MOST-SPRITE: explicit line associations, typed solution and provenance output.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from most_sprite.pipeline.echelle.models import SpectrumSet, WavelengthSolution


def solve_wavelength(
    calibration_spectra: SpectrumSet, line_list: Iterable[dict[str, Any]]
) -> WavelengthSolution:
    # Line records carry explicit order/pixel associations; the spectrum set
    # contributes the frozen configuration and provenance boundary.
    grouped: dict[int, list[tuple[float, float]]] = {}
    for line in line_list:
        grouped.setdefault(int(line["order"]), []).append(
            (float(line["pixel"]), float(line["wavelength_nm"]))
        )
    coefficients: dict[int, np.ndarray] = {}
    residual_rms: dict[int, float] = {}
    for order, matches in grouped.items():
        if len(matches) < 2:
            raise ValueError(f"order {order} needs at least two identified lines")
        values = np.asarray(matches, dtype=np.float64)
        degree = min(3, len(matches) - 1)
        coeff = np.polyfit(values[:, 0], values[:, 1], degree)
        residual = values[:, 1] - np.polyval(coeff, values[:, 0])
        coefficients[order] = coeff
        residual_rms[order] = float(np.sqrt(np.mean(residual**2)))
    return WavelengthSolution(
        coefficients=coefficients,
        residual_rms=residual_rms,
        config_version=calibration_spectra.config_version,
        provenance={
            "algorithm": "solve_wavelength",
            "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
        },
    )
