from __future__ import annotations

import numpy as np


def downsample_image(
    image: np.ndarray,
    *,
    max_width: int = 768,
    max_height: int = 384,
) -> np.ndarray:
    """Max-pool a 2-D detector image while preserving its aspect ratio.

    Narrow, bright echelle orders disappear under point sampling and can be
    diluted by mean pooling. Finite max pooling retains those structures and
    leaves non-finite-only blocks as NaN for the renderer to mark as missing.
    """
    if image.ndim != 2:
        raise ValueError("image must be two-dimensional")
    rows, columns = image.shape
    if rows < 1 or columns < 1:
        raise ValueError("image dimensions must be non-zero")
    if max_width < 1 or max_height < 1:
        raise ValueError("preview dimensions must be positive")

    scale = min(1.0, max_width / columns, max_height / rows)
    output_rows = max(1, min(rows, round(rows * scale)))
    output_columns = max(1, min(columns, round(columns * scale)))
    if (output_rows, output_columns) == image.shape:
        return np.asarray(image, dtype=np.float64)

    safe_image = np.where(np.isfinite(image), image, -np.inf)
    row_edges = np.linspace(0, rows, output_rows + 1, dtype=np.int64)
    column_starts = np.linspace(0, columns, output_columns + 1, dtype=np.int64)[:-1]
    sampled = np.empty((output_rows, output_columns), dtype=np.float64)
    for output_row, (row_start, row_end) in enumerate(
        zip(row_edges[:-1], row_edges[1:], strict=True)
    ):
        column_maxima = np.maximum.reduceat(
            safe_image[row_start:row_end], column_starts, axis=1
        )
        sampled[output_row] = np.max(column_maxima, axis=0)
    sampled[~np.isfinite(sampled)] = np.nan
    return sampled
