"""Flat modelling derived from audited GAMSE fibre-flat responsibilities.

Upstream: gamse/echelle/flat.py at commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9
Upstream SHA-256: 911be04891e5a6f9e97bd9997605429d949817fd2909f107532949b0e3e18ea7
Modified for MOST-SPRITE: versioned models, explicit uncertainty/DQ, no interactive effects.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.echelle.models import CalibrationFrame, FlatModel, TraceModel


def build_flat_model(master_flat: CalibrationFrame, trace: TraceModel) -> FlatModel:
    """Separate pixel response from the slowly varying order/blaze illumination."""
    smooth = median_filter(master_flat.data, size=(1, 31), mode="nearest")
    positive = smooth[np.isfinite(smooth) & (smooth > 0)]
    normalization = np.nanmedian(positive)
    if positive.size == 0 or not np.isfinite(normalization) or normalization <= 0:
        raise ValueError("master flat has no positive response")
    illuminated = smooth > max(0.01 * normalization, 1.0)
    response = np.ones(master_flat.data.shape, dtype=np.float64)
    np.divide(master_flat.data, smooth, out=response, where=illuminated)
    response_normalization = np.nanmedian(response[illuminated])
    response /= response_normalization
    dq = master_flat.dq.copy()
    invalid = ~np.isfinite(response) | (response <= 0) | ~illuminated
    dq[invalid] |= DQBit.BAD_PIXEL
    response[invalid] = 1.0
    blaze = np.nanmedian(smooth / normalization, axis=0)
    variance = np.full(response.shape, np.inf, dtype=np.float64)
    np.divide(
        master_flat.variance,
        smooth**2 * response_normalization**2,
        out=variance,
        where=illuminated,
    )
    return FlatModel(
        response=response,
        blaze=blaze,
        variance=variance,
        dq=dq,
        coordinates=master_flat.coordinates.copy(),
        config_version=master_flat.config_version,
        provenance={
            "algorithm": "espadons_pixel_response_v1",
            "trace_count": int(trace.order_ids.size),
            "illumination_threshold_electron": max(0.01 * normalization, 1.0),
            "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
        },
    )
