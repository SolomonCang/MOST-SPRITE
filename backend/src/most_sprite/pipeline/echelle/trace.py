"""Order tracing rewritten from the audited GAMSE aperture-finding approach.

Upstream: gamse/echelle/trace.py at commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9
Upstream SHA-256: cdd25076b208593d6c29f5141a217a66e6b634ebde991b6411b927009d54f37a
Modified for MOST-SPRITE: SPRITE types, explicit uncertainty/DQ, no plotting or global paths.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import find_peaks

from most_sprite.pipeline.echelle.models import CalibrationFrame, TraceModel


def trace_orders(master_flat: CalibrationFrame, geometry: dict[str, Any]) -> TraceModel:
    profile = np.nanmedian(master_flat.data, axis=1)
    baseline = np.nanpercentile(profile, 20)
    profile = np.clip(profile - baseline, 0, None)
    expected = int(geometry.get("trace_count", geometry.get("order_count", 4)))
    distance = max(2, master_flat.data.shape[0] // max(expected * 2, 1))
    peaks, properties = find_peaks(
        profile,
        distance=distance,
        prominence=max(np.nanmax(profile) * float(geometry.get("prominence", 0.02)), 1e-9),
    )
    if peaks.size < expected:
        raise ValueError(f"found {peaks.size} traces, expected at least {expected}")
    strongest = np.argsort(properties["prominences"])[-expected:]
    centers = np.sort(peaks[strongest]).astype(np.float64)
    coefficients = np.column_stack([np.zeros(expected), centers])
    widths = np.full(expected, float(geometry.get("width", 2.5)))
    first_order = int(geometry.get("first_order", 0))
    return TraceModel(
        order_ids=np.arange(first_order, first_order + expected, dtype=np.int32),
        coefficients=coefficients,
        widths=widths,
        config_version=master_flat.config_version,
        provenance={
            "algorithm": "trace_orders",
            "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
            "profile_axis": 1,
        },
    )
