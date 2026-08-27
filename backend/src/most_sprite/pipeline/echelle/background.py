"""Background estimation derived from GAMSE inter-order modelling responsibilities.

Upstream: gamse/echelle/background.py at commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9
Upstream SHA-256: f40e947079fa72306ac0ca2a13e0cc514f3a1f794e72e05d8b70cccd6e9c51a5
Modified for MOST-SPRITE: deterministic arrays, explicit background variance, no plotting.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from most_sprite.pipeline.echelle.models import CalibrationFrame, TraceModel


def estimate_background(
    frame: CalibrationFrame, trace: TraceModel
) -> tuple[np.ndarray, np.ndarray]:
    mask = np.zeros(frame.data.shape, dtype=bool)
    pixels = np.arange(frame.data.shape[1], dtype=np.float64)
    for centers, width in zip(trace.centers(pixels), trace.widths, strict=True):
        for column, center in enumerate(centers):
            lower = max(0, int(np.floor(center - 3 * width)))
            upper = min(frame.data.shape[0], int(np.ceil(center + 3 * width + 1)))
            mask[lower:upper, column] = True
    samples = np.where(mask, np.nan, frame.data)
    column_background = np.nanmedian(samples, axis=0)
    fallback = float(np.nanmedian(frame.data))
    column_background = np.nan_to_num(column_background, nan=fallback)
    column_background = median_filter(column_background, size=31, mode="nearest")
    background = np.broadcast_to(column_background, frame.data.shape).copy()
    residual = np.where(mask, np.nan, frame.data - background)
    variance = np.broadcast_to(np.nanvar(residual, axis=0), frame.data.shape).copy()
    return background, np.nan_to_num(variance, nan=np.inf)
