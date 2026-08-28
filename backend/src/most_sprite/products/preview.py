from __future__ import annotations

from collections.abc import Callable

import numpy as np

CoordinateMapper = Callable[
    [np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]
]


def order_trace_annotations(
    order_ids: np.ndarray,
    coefficients: np.ndarray,
    *,
    trace_shape: tuple[int, int],
    image_shape: tuple[int, int] | None = None,
    coordinate_mapper: CoordinateMapper | None = None,
    sample_count: int = 64,
) -> list[dict[str, object]]:
    """Serialize every valid echelle trace in normalized preview coordinates."""
    trace_rows, trace_columns = trace_shape
    display_rows, display_columns = image_shape or trace_shape
    if min(trace_rows, trace_columns, display_rows, display_columns) < 1:
        raise ValueError("trace and image dimensions must be positive")
    if len(order_ids) != len(coefficients):
        raise ValueError("every order must have one trace polynomial")
    if sample_count < 2:
        raise ValueError("at least two trace samples are required")

    dispersion = np.linspace(
        0.0,
        float(trace_columns - 1),
        min(sample_count, max(2, trace_columns)),
    )
    annotations: list[dict[str, object]] = []
    for order, polynomial in zip(order_ids, coefficients, strict=True):
        center = np.polyval(np.asarray(polynomial, dtype=np.float64), dispersion)
        valid = (
            np.isfinite(center)
            & (center >= 0)
            & (center <= trace_rows - 1)
        )
        trace_x = dispersion[valid]
        trace_y = center[valid]
        if coordinate_mapper is not None:
            display_x, display_y = coordinate_mapper(trace_x, trace_y)
        else:
            display_x, display_y = trace_x, trace_y
        visible = (
            np.isfinite(display_x)
            & np.isfinite(display_y)
            & (display_x >= 0)
            & (display_x <= display_columns - 1)
            & (display_y >= 0)
            & (display_y <= display_rows - 1)
        )
        if np.count_nonzero(visible) < 2:
            continue
        x_denominator = max(display_columns - 1, 1)
        y_denominator = max(display_rows - 1, 1)
        points = [
            [
                round(float(x) / x_denominator, 6),
                round(float(y) / y_denominator, 6),
            ]
            for x, y in zip(display_x[visible], display_y[visible], strict=True)
        ]
        annotations.append({"order": int(order), "points": points})
    return annotations


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
