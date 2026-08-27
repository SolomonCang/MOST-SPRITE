"""ESPaDOnS-specific curved-order tracing and dual-beam optimal extraction.

This is a side-effect-free rewrite of the responsibilities in
``gamse/pipelines/espadons/trace.py`` and ``gamse/echelle/extract.py`` at the
frozen GAMSE commit 4d91ead6d8380b75a5a445c2dae78429bc23e0c9.  It retains the
six-peak slicer profile's central valley and A/B peak convention, while using
SPRITE variance and DQ arrays throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares, linear_sum_assignment

from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.echelle.models import (
    CalibrationFrame,
    SpectrumChannel,
    SpectrumSet,
    TraceModel,
)


@dataclass(slots=True)
class ESPaDOnSTraceSet:
    combined: TraceModel
    beams: dict[str, TraceModel]
    config_version: str = "espadons-olapa-v1"
    provenance: dict[str, Any] = field(default_factory=dict)


def _clip_mean(values: NDArray[np.float64]) -> tuple[float, float, NDArray[np.bool_]]:
    mask = np.isfinite(values)
    for _ in range(8):
        selected = values[mask]
        if selected.size < 3:
            break
        center = float(np.mean(selected))
        sigma = float(np.std(selected))
        if sigma <= 0:
            break
        updated = mask & (values > center - 5 * sigma) & (values < center + 3 * sigma)
        if np.array_equal(updated, mask):
            break
        mask = updated
    selected = values[mask]
    return float(np.mean(selected)), float(np.std(selected)), mask


def _derivative(values: NDArray[np.float64]) -> NDArray[np.float64]:
    result = np.empty_like(values)
    if values.size < 2:
        result.fill(np.nan)
        return result
    result[0] = values[1] - values[0]
    result[-1] = values[-1] - values[-2]
    if values.size > 2:
        result[1:-1] = (values[2:] - values[:-2]) / 2.0
    return result


def _quadratic_extremum(values: NDArray[np.float64], index: int, *, maximum: bool) -> float:
    index = int(np.clip(index, 1, values.size - 2))
    local = values[index - 1 : index + 2]
    if not maximum:
        local = -local
    denominator = local[0] - 2 * local[1] + local[2]
    offset = 0.0 if denominator == 0 else 0.5 * (local[0] - local[2]) / denominator
    return float(index + np.clip(offset, -1.0, 1.0))


def _profile_landmarks(
    section: NDArray[np.float64], lower: int, upper: int
) -> tuple[float, float, float]:
    values = np.asarray(section[lower:upper], dtype=np.float64)
    if values.size < 16:
        raise ValueError("ESPaDOnS slicer profile is too narrow")
    background = np.linspace(values[0], values[-1], values.size)
    signal = values - background
    middle = values.size // 2
    v_lo, v_hi = max(1, middle - 4), min(values.size - 1, middle + 5)
    valley_index = v_lo + int(np.argmin(signal[v_lo:v_hi]))
    valley = _quadratic_extremum(signal, valley_index, maximum=False) + lower
    left_expected = int(round(valley - lower - 7))
    right_expected = int(round(valley - lower + 7))
    left_lo, left_hi = max(1, left_expected - 4), min(values.size - 1, left_expected + 5)
    right_lo, right_hi = max(1, right_expected - 4), min(values.size - 1, right_expected + 5)
    left_index = left_lo + int(np.argmax(signal[left_lo:left_hi]))
    right_index = right_lo + int(np.argmax(signal[right_lo:right_hi]))
    left = _quadratic_extremum(signal, left_index, maximum=True) + lower
    right = _quadratic_extremum(signal, right_index, maximum=True) + lower
    return valley, left, right


def _order_locations(section: NDArray[np.float64]) -> list[tuple[float, float, float]]:
    positive = np.clip(np.asarray(section, dtype=np.float64), 1e-3, None)
    all_x = np.arange(positive.size, dtype=np.float64)
    window_mask = np.ones(positive.shape, dtype=bool)
    width_coeff = np.polyfit([100.0, 1200.0], [30.0, 65.0], deg=1)
    gap_coeff = np.polyfit([100.0, 1200.0], [5.0, 33.0], deg=1)
    for start in range(positive.size):
        window = float(np.polyval(width_coeff, start))
        gap = float(np.polyval(gap_coeff, start))
        if window <= 0 or gap <= 0:
            window_mask[start] = False
            continue
        stop = start + int(window)
        if stop >= positive.size:
            break
        threshold = np.percentile(positive[start:stop], gap / window * 100.0)
        window_mask[start:stop][positive[start:stop] > threshold] = False
    background_mask = window_mask.copy()
    log_signal = np.log(positive)
    background_fit = np.full(positive.shape, np.median(log_signal))
    for _ in range(10):
        if background_mask.sum() < 20:
            break
        degree = min(13, int(background_mask.sum()) - 1)
        coefficients = np.polyfit(all_x[background_mask], log_signal[background_mask], degree)
        background_fit = np.polyval(coefficients, all_x)
        residual = log_signal - background_fit
        sigma = float(np.std(residual[background_mask]))
        updated = residual < 2.5 * max(sigma, 1e-6)
        if updated.sum() == background_mask.sum():
            break
        background_mask = updated
    residual = log_signal - background_fit
    sigma = float(np.std(residual[background_mask])) if background_mask.any() else 1.0
    aperture_pixels = np.flatnonzero(residual > 3.0 * max(sigma, 1e-6))
    if aperture_pixels.size == 0:
        return []
    regions = [
        (int(group[0]), int(group[-1]) + 1)
        for group in np.split(aperture_pixels, np.where(np.diff(aperture_pixels) >= 3)[0] + 1)
        if group.size and int(group[-1]) - int(group[0]) + 1 >= 20
    ]
    if len(regions) < 3:
        return []
    positions = np.asarray([(lower + upper) / 2 for lower, upper in regions])
    widths = np.asarray([upper - lower for lower, upper in regions], dtype=np.float64)
    separations = _derivative(positions)
    width_mean, width_std, width_mask = _clip_mean(widths)
    separation_mask = np.isfinite(separations) & width_mask
    degree = min(3, max(1, int(separation_mask.sum()) - 1))
    separation_fit = np.polyfit(
        positions[separation_mask], separations[separation_mask], degree
    )
    wide = widths > width_mean + 3 * max(width_std, 1.0)
    split_regions: list[tuple[int, int]] = []
    for index, (lower, upper) in enumerate(regions):
        if not wide[index]:
            split_regions.append((lower, upper))
            continue
        local_separation = float(np.polyval(separation_fit, (lower + upper) / 2))
        count = max(1, int(round((upper - lower) / max(local_separation, 1.0))))
        boundaries = [lower]
        for split_index in range(1, count):
            expected = lower + (upper - lower) * split_index / count
            radius = max(2, int(local_separation / 4))
            lo = max(lower, int(expected) - radius)
            hi = min(upper, int(expected) + radius + 1)
            boundaries.append(lo + int(np.argmin(positive[lo:hi])))
        boundaries.append(upper)
        split_regions.extend(zip(boundaries[:-1], boundaries[1:], strict=True))
    landmarks: list[tuple[float, float, float]] = []
    for lower, upper in split_regions:
        try:
            landmarks.append(_profile_landmarks(positive, lower, upper))
        except (ValueError, IndexError):
            continue
    return landmarks


def _section_alignment(
    previous: NDArray[np.float64], current: NDArray[np.float64]
) -> tuple[float, float, float]:
    """Fit the local affine detector warp between adjacent scan columns."""
    pixels = np.arange(previous.size, dtype=np.float64)
    previous_log = np.log(np.clip(previous, 1e-3, None))
    current_log = np.log(np.clip(current, 1e-3, None))
    mask = (
        (pixels >= 20)
        & (pixels < pixels.size - 20)
        & np.isfinite(previous_log)
        & np.isfinite(current_log)
    )
    sample_pixels = pixels[mask]

    def residual(parameters: NDArray[np.float64]) -> NDArray[np.float64]:
        scale, shift, offset = parameters
        sampled = np.interp(
            scale * sample_pixels + shift,
            pixels,
            current_log,
            left=np.nan,
            right=np.nan,
        )
        values = sampled + offset - previous_log[mask]
        return np.nan_to_num(values, nan=10.0, posinf=10.0, neginf=-10.0)

    initial = np.asarray(
        [1.0, 0.0, float(np.nanmedian(previous_log[mask] - current_log[mask]))]
    )
    result = least_squares(
        residual,
        initial,
        bounds=([0.97, -30.0, -5.0], [1.03, 30.0, 5.0]),
        loss="soft_l1",
        f_scale=0.15,
        max_nfev=100,
    )
    if not result.success:
        raise ValueError("ESPaDOnS scan-column alignment did not converge")
    scale, shift, _ = (float(value) for value in result.x)
    rms = float(np.sqrt(np.mean(residual(result.x) ** 2)))
    return scale, shift, rms


def _select_olapa_polarimetric_anchors(
    locations: list[tuple[float, float, float]],
    *,
    expected_orders: int,
) -> list[tuple[float, float, float]]:
    ordered_locations = sorted(locations, key=lambda value: value[0])
    if len(ordered_locations) == expected_orders:
        return ordered_locations
    if len(ordered_locations) != expected_orders + 1:
        raise ValueError(
            f"found {len(ordered_locations)} central ESPaDOnS profiles; "
            f"expected {expected_orders} or {expected_orders + 1}"
        )
    return [
        location
        for index, location in enumerate(ordered_locations)
        if index != 1
    ]


def _track_landmarks(
    samples: list[
        tuple[float, NDArray[np.float64], list[tuple[float, float, float]]]
    ],
    *,
    expected_orders: int,
    detector_rows: int,
    max_aligned_distance: float = 6.0,
) -> tuple[
    list[list[tuple[float, tuple[float, float, float]]]], dict[str, Any]
]:
    if not samples:
        return [], {}
    # Pick the middle of the sampled dispersion interval instead of relying on
    # OLAPA's nominal 4608-pixel width.  This keeps the detector algorithm
    # valid for windowed calibration frames and for deterministic unit tests.
    dispersion_midpoint = (
        min(sample[0] for sample in samples) + max(sample[0] for sample in samples)
    ) / 2.0
    center_index = min(
        range(len(samples)),
        key=lambda index: abs(samples[index][0] - dispersion_midpoint),
    )
    center_x, _, center_values = samples[center_index]
    # Current OLAPA flats expose the forty m=22..61 slicer profiles directly.
    # Some legacy red-edge geometries expose a 41st profile: in canonical
    # coordinates the clipped m=22 profile is first, reference-only m=21 is
    # second, and m=23..61 follow.  This ordering is verified against the
    # immutable GAMSE lamp (profile 1 correlates with m=21; profile 2 with
    # m=23).  The downstream same-night ThAr solver additionally requires 200
    # associations across 30 physical orders, so an incorrect inventory cannot
    # pass on a few aliases.
    anchors = _select_olapa_polarimetric_anchors(
        center_values,
        expected_orders=expected_orders,
    )
    anchor_centers = np.asarray([value[0] for value in anchors], dtype=np.float64)
    mappings: dict[int, tuple[float, float]] = {center_index: (1.0, 0.0)}
    alignment_rms: dict[int, float] = {center_index: 0.0}
    for indices in (
        range(center_index - 1, -1, -1),
        range(center_index + 1, len(samples)),
    ):
        previous_index = center_index
        for sample_index in indices:
            scale, shift, rms = _section_alignment(
                samples[previous_index][1], samples[sample_index][1]
            )
            previous_scale, previous_shift = mappings[previous_index]
            mappings[sample_index] = (
                previous_scale / scale,
                previous_shift - previous_scale * shift / scale,
            )
            alignment_rms[sample_index] = rms
            previous_index = sample_index

    tracks: list[list[tuple[float, tuple[float, float, float]]]] = [
        [] for _ in anchors
    ]
    match_distances: list[float] = []
    for sample_index, (dispersion, _, locations) in enumerate(samples):
        scale, shift = mappings[sample_index]
        aligned = np.asarray(
            [scale * value[0] + shift for value in locations], dtype=np.float64
        )
        cost = np.abs(anchor_centers[:, None] - aligned[None, :])
        track_indices, location_indices = linear_sum_assignment(cost)
        for track_index, location_index in zip(
            track_indices, location_indices, strict=True
        ):
            distance = float(cost[track_index, location_index])
            if distance <= max_aligned_distance:
                tracks[int(track_index)].append(
                    (dispersion, locations[int(location_index)])
                )
                match_distances.append(distance)
    minimum_samples = max(8, len(samples) // 3)
    if any(len(track) < minimum_samples for track in tracks):
        counts = [len(track) for track in tracks]
        raise ValueError(
            "one or more ESPaDOnS orders lack stable scan-column coverage: "
            f"minimum={min(counts)}, required={minimum_samples}"
        )
    return tracks, {
        "central_dispersion_pixel": center_x,
        "central_profile_count": len(center_values),
        "excluded_reference_profile_index": (
            1 if len(center_values) == expected_orders + 1 else None
        ),
        "excluded_physical_order": (
            21 if len(center_values) == expected_orders + 1 else None
        ),
        "retained_physical_order_range": [22, 61],
        "alignment_rms_median": float(np.median(list(alignment_rms.values()))),
        "alignment_rms_max": float(np.max(list(alignment_rms.values()))),
        "match_distance_median_pixel": float(np.median(match_distances)),
        "match_distance_max_pixel": float(np.max(match_distances)),
        "minimum_track_samples": min(len(track) for track in tracks),
    }


def trace_espadons_orders(
    master_flat: CalibrationFrame,
    *,
    expected_orders: int = 40,
    scan_step: int = 100,
    polynomial_degree: int = 5,
) -> ESPaDOnSTraceSet:
    data = master_flat.data
    sample_pixels = np.unique(
        np.concatenate(
            (
                np.arange(20, data.shape[1] - 20, scan_step),
                np.asarray([data.shape[1] // 2]),
            )
        )
    )
    samples: list[
        tuple[float, NDArray[np.float64], list[tuple[float, float, float]]]
    ] = []
    for dispersion in sample_pixels:
        lower = max(0, int(dispersion) - 2)
        upper = min(data.shape[1], int(dispersion) + 3)
        section = np.nanmean(data[:, lower:upper], axis=1)
        locations = _order_locations(section)
        if locations:
            samples.append((float(dispersion), section, locations))
    tracks, alignment_qc = _track_landmarks(
        samples,
        expected_orders=expected_orders,
        detector_rows=data.shape[0],
    )
    order_ids = np.arange(22, 22 + expected_orders, dtype=np.int32)
    role_coefficients: dict[str, list[NDArray[np.float64]]] = {
        "COMBINED": [],
        "O_BEAM": [],
        "E_BEAM": [],
    }
    residuals: dict[str, list[float]] = {key: [] for key in role_coefficients}
    fit_counts: dict[str, list[int]] = {key: [] for key in role_coefficients}
    raw_offsets: dict[str, list[float]] = {"O_BEAM": [], "E_BEAM": []}
    for track in tracks:
        for _, landmarks in track:
            for role, landmark_index, bounds in (
                ("O_BEAM", 1, (-12.0, -3.0)),
                ("E_BEAM", 2, (3.0, 12.0)),
            ):
                offset = float(landmarks[landmark_index] - landmarks[0])
                if bounds[0] <= offset <= bounds[1]:
                    raw_offsets[role].append(offset)
    beam_offsets = {
        role: float(np.median(values)) for role, values in raw_offsets.items()
    }
    beam_offset_scatter = {
        role: float(
            1.4826 * np.median(np.abs(values - np.median(values)))
        )
        for role, raw_values in raw_offsets.items()
        for values in (np.asarray(raw_values, dtype=np.float64),)
    }

    def robust_fit(
        x: NDArray[np.float64],
        y: NDArray[np.float64],
        *,
        degree: int,
        mask: NDArray[np.bool_],
        minimum_samples: int,
    ) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
        if mask.sum() < minimum_samples:
            raise ValueError("ESPaDOnS trace landmark coverage is insufficient")
        fit_degree = min(degree, int(mask.sum()) - 1)
        coefficients = np.polyfit(x[mask], y[mask], fit_degree)
        for _ in range(8):
            residual = y - np.polyval(coefficients, x)
            center = float(np.median(residual[mask]))
            sigma = float(
                1.4826 * np.median(np.abs(residual[mask] - center))
            )
            clip = max(min(3.0 * sigma, 1.0), 0.15)
            updated = mask & (np.abs(residual - center) <= clip)
            if np.array_equal(updated, mask) or updated.sum() < minimum_samples:
                break
            mask = updated
            fit_degree = min(degree, int(mask.sum()) - 1)
            coefficients = np.polyfit(
                x[mask], y[mask], fit_degree
            )
        return np.asarray(coefficients, dtype=np.float64), mask

    for track in tracks:
        x = np.asarray([item[0] for item in track], dtype=np.float64)
        combined_landmarks = np.asarray(
            [item[1][0] for item in track], dtype=np.float64
        )
        combined_coefficients, combined_mask = robust_fit(
            x,
            combined_landmarks,
            degree=polynomial_degree,
            mask=np.ones(x.shape, dtype=bool),
            minimum_samples=max(polynomial_degree + 2, x.size // 2),
        )
        role_coefficients["COMBINED"].append(combined_coefficients)
        combined_residual = combined_landmarks[combined_mask] - np.polyval(
            combined_coefficients, x[combined_mask]
        )
        residuals["COMBINED"].append(
            float(np.sqrt(np.mean(combined_residual**2)))
        )
        fit_counts["COMBINED"].append(int(combined_mask.sum()))

        for role in ("O_BEAM", "E_BEAM"):
            coefficients = combined_coefficients.copy()
            coefficients[-1] += beam_offsets[role]
            role_coefficients[role].append(coefficients)
            residuals[role].append(
                float(np.sqrt(np.mean(combined_residual**2)))
            )
            fit_counts[role].append(int(combined_mask.sum()))

    def model(role: str, width: float) -> TraceModel:
        return TraceModel(
            order_ids=order_ids.copy(),
            coefficients=np.asarray(role_coefficients[role], dtype=np.float64),
            widths=np.full(expected_orders, width, dtype=np.float64),
            config_version=master_flat.config_version,
            provenance={
                "algorithm": "espadons_curved_trace_v2",
                "role": role,
                "fit_rms_pixel": residuals[role],
                "fit_sample_count": fit_counts[role],
                "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
            },
        )

    combined = model("COMBINED", 15.0)
    beams = {"O_BEAM": model("O_BEAM", 6.0), "E_BEAM": model("E_BEAM", 6.0)}
    all_residuals = residuals["O_BEAM"] + residuals["E_BEAM"]
    return ESPaDOnSTraceSet(
        combined=combined,
        beams=beams,
        config_version=master_flat.config_version,
        provenance={
            "algorithm": "espadons_curved_trace_v2",
            "order_selection": "olapa-polarimetric-m22-m61-v1",
            "order_count": expected_orders,
            "sample_count": len(samples),
            "trace_rms_pixel": float(np.median(all_residuals)),
            "trace_rms_p90_pixel": float(np.quantile(all_residuals, 0.9)),
            "trace_rms_max_pixel": float(np.max(all_residuals)),
            "alignment": alignment_qc,
            "beam_geometry": {
                "algorithm": "olapa-slicer-global-offset-v1",
                "offset_pixel": beam_offsets,
                "raw_landmark_robust_scatter_pixel": beam_offset_scatter,
                "raw_landmark_count": {
                    role: len(values) for role, values in raw_offsets.items()
                },
            },
            "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
        },
    )


def build_spatial_profile(
    master_flat: CalibrationFrame, trace_set: ESPaDOnSTraceSet
) -> NDArray[np.float64]:
    profile = np.zeros(master_flat.data.shape, dtype=np.float64)
    pixels = np.arange(master_flat.data.shape[1], dtype=np.float64)
    for trace in trace_set.beams.values():
        centers = trace.centers(pixels)
        for trace_index, center in enumerate(centers):
            radius = int(np.ceil(trace.widths[trace_index]))
            for column, row_center in enumerate(center):
                lower = max(0, int(np.floor(row_center - radius)))
                upper = min(master_flat.data.shape[0], int(np.ceil(row_center + radius + 1)))
                values = np.clip(master_flat.data[lower:upper, column], 0.0, None)
                total = float(np.sum(values))
                if total > 0:
                    profile[lower:upper, column] = np.maximum(
                        profile[lower:upper, column], values / total
                    )
    return profile


def estimate_multiorder_background(
    frame: CalibrationFrame, trace_set: ESPaDOnSTraceSet
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    mask = np.zeros(frame.data.shape, dtype=bool)
    pixels = np.arange(frame.data.shape[1], dtype=np.float64)
    for centers, width in zip(
        trace_set.combined.centers(pixels), trace_set.combined.widths, strict=True
    ):
        for column, center in enumerate(centers):
            lower = max(0, int(np.floor(center - width)))
            upper = min(frame.data.shape[0], int(np.ceil(center + width + 1)))
            mask[lower:upper, column] = True
    samples = np.where(mask, np.nan, frame.data)
    background_1d = np.nanmedian(samples, axis=0)
    global_background = float(np.nanmedian(frame.data[~mask])) if np.any(~mask) else 0.0
    background_1d = np.nan_to_num(background_1d, nan=global_background)
    background = np.broadcast_to(background_1d, frame.data.shape).copy()
    residual = np.where(mask, np.nan, frame.data - background)
    background_variance = np.nanvar(residual, axis=0)
    background_variance = np.nan_to_num(background_variance, nan=np.inf)
    return background, np.broadcast_to(background_variance, frame.data.shape).copy()


def extract_espadons_beams(
    frame: CalibrationFrame,
    trace_set: ESPaDOnSTraceSet,
    spatial_profile: NDArray[np.float64],
    *,
    cosmic_sigma: float = 5.0,
    cosmic_min_fraction: float = 0.5,
) -> SpectrumSet:
    if spatial_profile.shape != frame.data.shape:
        raise ValueError("spatial profile and L1 frame shapes differ")
    background, background_variance = estimate_multiorder_background(frame, trace_set)
    data = frame.data - background
    variance_image = frame.variance + background_variance
    pixels = np.arange(frame.data.shape[1], dtype=np.float64)
    channels: dict[str, SpectrumChannel] = {}
    for role, trace in trace_set.beams.items():
        center_grid = trace.centers(pixels)
        flux_parts: list[NDArray[np.float64]] = []
        variance_parts: list[NDArray[np.float64]] = []
        dq_parts: list[NDArray[np.uint32]] = []
        order_parts: list[NDArray[np.int32]] = []
        for trace_index, order in enumerate(trace.order_ids):
            flux = np.full(pixels.shape, np.nan, dtype=np.float64)
            variance = np.full(pixels.shape, np.inf, dtype=np.float64)
            dq = np.zeros(pixels.shape, dtype=np.uint32)
            radius = int(np.ceil(trace.widths[trace_index]))
            for column, center in enumerate(center_grid[trace_index]):
                lower = max(0, int(np.floor(center - radius)))
                upper = min(frame.data.shape[0], int(np.ceil(center + radius + 1)))
                values = data[lower:upper, column]
                variances = variance_image[lower:upper, column]
                quality = frame.dq[lower:upper, column]
                profile = np.clip(spatial_profile[lower:upper, column], 0.0, None)
                valid = (
                    np.isfinite(values)
                    & np.isfinite(variances)
                    & (variances > 0)
                    & (profile > 0)
                    & ((quality & (DQBit.SATURATED | DQBit.BAD_PIXEL)) == 0)
                )
                if valid.sum() < 3:
                    dq[column] = np.bitwise_or.reduce(quality, initial=0)
                    dq[column] |= DQBit.EXTRACTION_FAILED
                    continue
                normalized = profile[valid] / np.sum(profile[valid])
                denominator = np.sum(normalized**2 / variances[valid])
                if denominator <= 0:
                    dq[column] |= DQBit.EXTRACTION_FAILED
                    continue
                estimate = np.sum(normalized * values[valid] / variances[valid]) / denominator
                model = estimate * normalized
                residual = values[valid] - model

                # The six-slice ESPaDOnS profile changes slightly with
                # retarder state and illumination.  A plain per-pixel
                # ``N sigma`` test therefore mistakes coherent profile
                # mismatch for cosmic rays, especially in high-S/N blue
                # orders.  Cosmic rays are positive, isolated excursions.
                # Estimate the local residual scatter robustly and only
                # reject a candidate that is also large compared with the
                # fitted local profile.  At most one detector pixel is
                # rejected per spatial cut before the optimal estimate is
                # recomputed.
                standardized = residual / np.sqrt(variances[valid])
                residual_center = float(np.median(standardized))
                residual_scale = float(
                    1.4826
                    * np.median(np.abs(standardized - residual_center))
                )
                candidate = int(np.argmax(standardized))
                candidate_is_cosmic = bool(
                    standardized[candidate]
                    > residual_center + cosmic_sigma * max(1.0, residual_scale)
                    and residual[candidate]
                    > cosmic_min_fraction * max(abs(model[candidate]), 1.0)
                )
                rejected = np.zeros(valid.sum(), dtype=bool)
                if candidate_is_cosmic:
                    rejected[candidate] = True
                if candidate_is_cosmic and (~rejected).sum() >= 3:
                    kept = ~rejected
                    p_kept = normalized[kept]
                    p_kept /= np.sum(p_kept)
                    denominator = np.sum(p_kept**2 / variances[valid][kept])
                    estimate = (
                        np.sum(p_kept * values[valid][kept] / variances[valid][kept])
                        / denominator
                    )
                    dq[column] |= DQBit.COSMIC_RAY
                flux[column] = estimate
                variance[column] = 1.0 / denominator
                dq[column] |= np.bitwise_or.reduce(quality, initial=0)
            flux_parts.append(flux)
            variance_parts.append(variance)
            dq_parts.append(dq)
            order_parts.append(np.full(pixels.shape, order, dtype=np.int32))
        channels[role] = SpectrumChannel(
            role=role,
            order=np.concatenate(order_parts),
            pixel=np.tile(pixels, trace.order_ids.size),
            wavelength=np.full(pixels.size * trace.order_ids.size, np.nan),
            flux=np.concatenate(flux_parts),
            variance=np.concatenate(variance_parts),
            dq=np.concatenate(dq_parts),
            unit=frame.unit,
            config_version=trace_set.config_version,
            provenance={
                "algorithm": "espadons_optimal_extraction_v1",
                "background": "interorder_column_median_v1",
                "cosmic_sigma": cosmic_sigma,
                "cosmic_rejection": "positive-adaptive-profile-v1",
                "cosmic_min_fraction": cosmic_min_fraction,
                "source_commit": "4d91ead6d8380b75a5a445c2dae78429bc23e0c9",
            },
        )
    return SpectrumSet(
        channels=channels,
        native_grid=True,
        config_version=trace_set.config_version,
        provenance={
            "common_grid_resampling_count": 0,
            "algorithm": "espadons_dual_beam_extraction_v1",
        },
    )
