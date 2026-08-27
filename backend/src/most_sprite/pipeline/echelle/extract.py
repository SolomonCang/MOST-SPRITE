"""Channel extraction rewritten from audited GAMSE multi-fibre extraction concepts.

Upstream: gamse/echelle/extract.py at commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9
Upstream SHA-256: f4391bcf05da78557fbb5c7b301f3aba8b34787ba689f0663473b32c12afadf5
Modified for MOST-SPRITE: named channels, explicit coordinates/VAR/DQ, no file discovery.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from most_sprite.pipeline.echelle.models import (
    CalibrationFrame,
    SpectrumChannel,
    SpectrumSet,
    TraceModel,
)


def extract_channels(
    l1_frame: CalibrationFrame, trace: TraceModel, channel_map: dict[str, list[int] | Any]
) -> SpectrumSet:
    pixels = np.arange(l1_frame.data.shape[1], dtype=np.float64)
    center_grid = trace.centers(pixels)
    channels: dict[str, SpectrumChannel] = {}
    for role, trace_indices in channel_map.items():
        flux_parts: list[np.ndarray] = []
        variance_parts: list[np.ndarray] = []
        dq_parts: list[np.ndarray] = []
        order_parts: list[np.ndarray] = []
        pixel_parts: list[np.ndarray] = []
        for trace_index in trace_indices:
            center = center_grid[trace_index]
            width = trace.widths[trace_index]
            flux = np.zeros_like(pixels)
            variance = np.zeros_like(pixels)
            dq = np.zeros(pixels.shape, dtype=np.uint32)
            for column, row_center in enumerate(center):
                lower = max(0, int(np.floor(row_center - 2 * width)))
                upper = min(l1_frame.data.shape[0], int(np.ceil(row_center + 2 * width + 1)))
                flux[column] = np.nansum(l1_frame.data[lower:upper, column])
                variance[column] = np.nansum(l1_frame.variance[lower:upper, column])
                dq[column] = np.bitwise_or.reduce(l1_frame.dq[lower:upper, column], initial=0)
            flux_parts.append(flux)
            variance_parts.append(variance)
            dq_parts.append(dq)
            order_parts.append(np.full(pixels.shape, trace.order_ids[trace_index], dtype=np.int32))
            pixel_parts.append(pixels.copy())
        merged_pixel = np.concatenate(pixel_parts)
        channels[role] = SpectrumChannel(
            role=role,
            order=np.concatenate(order_parts),
            pixel=merged_pixel,
            wavelength=np.full(merged_pixel.shape, np.nan),
            flux=np.concatenate(flux_parts),
            variance=np.concatenate(variance_parts),
            dq=np.concatenate(dq_parts),
            unit=l1_frame.unit,
            config_version=l1_frame.config_version,
            provenance={
                "algorithm": "extract_channels",
                "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
            },
        )
    return SpectrumSet(
        channels=channels,
        config_version=l1_frame.config_version,
        provenance={"channel_map": channel_map},
    )
