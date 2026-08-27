"""Calibration combination rewritten from audited GAMSE image-combination concepts.

Upstream: gamse/echelle/imageproc.py at commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9
Upstream SHA-256: 4d161894c550a5946458e6b34e7f3b077e89c0c18b8a91d7f534a429273b9f3f
Modified for MOST-SPRITE: immutable inputs, explicit VAR/DQ, no plotting or global paths.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from most_sprite.pipeline.echelle.models import CalibrationFrame


def combine_calibration(
    frames: Iterable[CalibrationFrame | np.ndarray], detector_model: dict[str, Any]
) -> CalibrationFrame:
    items = list(frames)
    if not items:
        raise ValueError("at least one calibration frame is required")
    sources = [
        item.data if isinstance(item, CalibrationFrame) else np.asarray(item)
        for item in items
    ]
    shape = sources[0].shape
    if len(shape) != 2 or any(source.shape != shape for source in sources):
        raise ValueError("calibration frames must share one two-dimensional shape")

    data = np.empty(shape, dtype=np.float64)
    variance = np.empty(shape, dtype=np.float64)
    dq = np.zeros(shape, dtype=np.uint32)
    working_bytes = int(detector_model.get("working_memory_bytes", 256 * 1024 * 1024))
    bytes_per_row = max(1, len(items) * shape[1] * 8 * 4)
    tile_rows = max(1, min(shape[0], working_bytes // bytes_per_row))
    read_noise = float(detector_model.get("read_noise_e", 0.0))
    minimum_count = max(1, len(items) // 2)
    degrees_of_freedom = 1 if len(items) > 1 else 0

    for lower in range(0, shape[0], tile_rows):
        upper = min(shape[0], lower + tile_rows)
        arrays = np.stack(
            [source[lower:upper] for source in sources],
            axis=0,
        ).astype(np.float64, copy=False)
        median = np.nanmedian(arrays, axis=0)
        mad = np.nanmedian(np.abs(arrays - median), axis=0)
        sigma = np.maximum(1.4826 * mad, read_noise)
        accepted = np.abs(arrays - median) <= 5.0 * np.where(sigma > 0, sigma, 1.0)
        clipped = np.where(accepted, arrays, np.nan)
        finite_count = np.sum(np.isfinite(clipped), axis=0)
        safe_count = np.maximum(finite_count, 1)
        data[lower:upper] = np.nanmean(clipped, axis=0)
        tile_variance = (
            np.nanvar(clipped, axis=0, ddof=degrees_of_freedom) / safe_count
        )
        variance[lower:upper] = np.nan_to_num(tile_variance, nan=np.inf)
        tile_dq = dq[lower:upper]
        tile_dq[finite_count < minimum_count] |= 1 << 2
    return CalibrationFrame(
        data=data,
        variance=variance,
        dq=dq,
        unit=items[0].unit if isinstance(items[0], CalibrationFrame) else "adu",
        coordinates=(items[0].coordinates.copy() if isinstance(items[0], CalibrationFrame) else {}),
        config_version=str(detector_model.get("config_version", "UNVERIFIED")),
        provenance={
            "algorithm": "combine_calibration",
            "input_count": len(items),
            "clip_sigma": 5.0,
            "tile_rows": tile_rows,
            "working_memory_bytes": working_bytes,
            "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
        },
    )
