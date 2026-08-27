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
    arrays = np.stack(
        [item.data if isinstance(item, CalibrationFrame) else np.asarray(item) for item in items]
    ).astype(np.float64)
    median = np.nanmedian(arrays, axis=0)
    mad = np.nanmedian(np.abs(arrays - median), axis=0)
    sigma = np.maximum(1.4826 * mad, float(detector_model.get("read_noise_e", 0.0)))
    accepted = np.abs(arrays - median) <= 5.0 * np.where(sigma > 0, sigma, 1.0)
    clipped = np.where(accepted, arrays, np.nan)
    data = np.nanmean(clipped, axis=0)
    count = np.maximum(np.sum(np.isfinite(clipped), axis=0), 1)
    variance = np.nanvar(clipped, axis=0, ddof=1 if len(items) > 1 else 0) / count
    dq = np.zeros(data.shape, dtype=np.uint32)
    dq[count < max(1, len(items) // 2)] |= 1 << 2
    return CalibrationFrame(
        data=data,
        variance=np.nan_to_num(variance, nan=np.inf),
        dq=dq,
        unit=items[0].unit if isinstance(items[0], CalibrationFrame) else "adu",
        coordinates=(items[0].coordinates.copy() if isinstance(items[0], CalibrationFrame) else {}),
        config_version=str(detector_model.get("config_version", "UNVERIFIED")),
        provenance={
            "algorithm": "combine_calibration",
            "input_count": len(items),
            "clip_sigma": 5.0,
            "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
        },
    )
