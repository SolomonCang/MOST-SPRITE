from __future__ import annotations

import numpy as np

from most_sprite.configuration import default_instrument_configuration
from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.echelle.models import SpectrumChannel, SpectrumSet, WavelengthSolution
from most_sprite.pipeline.echelle.wlcalib import solve_wavelength
from most_sprite.pipeline.simulation import wavelength_grid


def apply_wavelength_solution(spectra: SpectrumSet, solution: WavelengthSolution) -> SpectrumSet:
    """Attach an explicit wavelength solution without changing the native pixels."""
    if spectra.config_version != solution.config_version:
        raise ValueError("spectrum and wavelength solution configuration versions differ")
    channels: dict[str, SpectrumChannel] = {}
    for role, channel in spectra.channels.items():
        wavelength = np.full(channel.pixel.shape, np.nan, dtype=np.float64)
        dq = channel.dq.copy()
        for order in np.unique(channel.order):
            selection = channel.order == order
            role_coefficients = solution.channel_coefficients.get(role, {})
            if int(order) not in role_coefficients and int(order) not in solution.coefficients:
                dq[selection] |= DQBit.MISSING_CALIBRATION
                continue
            wavelength[selection] = solution.evaluate(
                int(order), channel.pixel[selection], role=role
            )
        channels[role] = SpectrumChannel(
            role=channel.role,
            order=channel.order.copy(),
            pixel=channel.pixel.copy(),
            wavelength=wavelength,
            flux=channel.flux.copy(),
            variance=channel.variance.copy(),
            dq=dq,
            covariance_lag1=(
                channel.covariance_lag1.copy()
                if channel.covariance_lag1 is not None
                else None
            ),
            unit=channel.unit,
            wavelength_unit=solution.unit,
            config_version=channel.config_version,
            provenance={
                **channel.provenance,
                "wavelength_algorithm": "polynomial-per-order-v1",
                "wavelength_type": solution.wavelength_type,
                "wavelength_solution": solution.provenance,
            },
        )
    return SpectrumSet(
        channels=channels,
        native_grid=True,
        config_version=spectra.config_version,
        provenance={
            **spectra.provenance,
            "wavelength_solution_applied": True,
            "common_grid_resampling_count": int(
                spectra.provenance.get("common_grid_resampling_count", 0)
            ),
        },
    )


def _bin_edges(centers: np.ndarray) -> np.ndarray:
    if centers.size < 2 or np.any(np.diff(centers) <= 0):
        raise ValueError("wavelength coordinates must be strictly increasing")
    midpoint = (centers[:-1] + centers[1:]) / 2.0
    return np.concatenate(
        (
            [centers[0] - (midpoint[0] - centers[0])],
            midpoint,
            [centers[-1] + (centers[-1] - midpoint[-1])],
        )
    )


def _flux_conserving_resample(
    source_x: np.ndarray,
    source_y: np.ndarray,
    source_variance: np.ndarray,
    source_dq: np.ndarray,
    target_x: np.ndarray,
    source_covariance_lag1: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    source_x = np.asarray(source_x, dtype=np.float64)
    source_y = np.asarray(source_y, dtype=np.float64)
    source_variance = np.asarray(source_variance, dtype=np.float64)
    source_dq = np.asarray(source_dq, dtype=np.uint32)
    if source_x.size >= 2 and source_x[0] > source_x[-1]:
        source_x = source_x[::-1]
        source_y = source_y[::-1]
        source_variance = source_variance[::-1]
        source_dq = source_dq[::-1]
        if source_covariance_lag1 is not None:
            source_covariance_lag1 = np.asarray(source_covariance_lag1)[::-1]
    source_edges = _bin_edges(source_x)
    target_edges = _bin_edges(np.asarray(target_x, dtype=np.float64))
    source_width = np.diff(source_edges)
    weights: list[dict[int, float]] = [dict() for _ in range(target_x.size)]
    source_index = 0
    for target_index in range(target_x.size):
        lower = target_edges[target_index]
        upper = target_edges[target_index + 1]
        while source_index < source_x.size and source_edges[source_index + 1] <= lower:
            source_index += 1
        candidate = source_index
        while candidate < source_x.size and source_edges[candidate] < upper:
            overlap = max(
                0.0,
                min(upper, source_edges[candidate + 1])
                - max(lower, source_edges[candidate]),
            )
            if overlap > 0 and source_width[candidate] > 0:
                weights[target_index][candidate] = overlap / source_width[candidate]
            candidate += 1
    flux = np.full(target_x.shape, np.nan, dtype=np.float64)
    variance = np.full(target_x.shape, np.inf, dtype=np.float64)
    covariance_lag1 = np.zeros(target_x.shape, dtype=np.float64)
    dq = np.zeros(target_x.shape, dtype=np.uint32)
    input_lag = (
        np.zeros(source_x.shape, dtype=np.float64)
        if source_covariance_lag1 is None
        else np.asarray(source_covariance_lag1, dtype=np.float64)
    )
    for target_index, mapping in enumerate(weights):
        if not mapping:
            dq[target_index] |= DQBit.RESAMPLE_EDGE
            continue
        indices = np.asarray(sorted(mapping), dtype=np.int64)
        coefficient = np.asarray([mapping[int(index)] for index in indices])
        valid = (
            np.isfinite(source_y[indices])
            & np.isfinite(source_variance[indices])
            & (source_variance[indices] >= 0)
        )
        if not valid.any():
            dq[target_index] |= DQBit.RESAMPLE_EDGE
            continue
        indices = indices[valid]
        coefficient = coefficient[valid]
        flux[target_index] = float(np.sum(coefficient * source_y[indices]))
        value_variance = float(np.sum(coefficient**2 * source_variance[indices]))
        for left, right in zip(indices[:-1], indices[1:], strict=True):
            if right == left + 1:
                value_variance += float(
                    2
                    * mapping[int(left)]
                    * mapping[int(right)]
                    * input_lag[int(left)]
                )
        variance[target_index] = max(value_variance, 0.0)
        dq[target_index] = np.bitwise_or.reduce(source_dq[indices], initial=0)
    for target_index in range(target_x.size - 1):
        first = weights[target_index]
        second = weights[target_index + 1]
        shared = set(first) & set(second)
        value = sum(
            first[index] * second[index] * source_variance[index] for index in shared
        )
        for first_index, first_weight in first.items():
            for second_index in (first_index - 1, first_index + 1):
                if second_index in second:
                    lag_index = min(first_index, second_index)
                    value += first_weight * second[second_index] * input_lag[lag_index]
        covariance_lag1[target_index] = value
    return flux, variance, dq, covariance_lag1


def resample_common_grid(
    spectra: SpectrumSet, grids_by_order: dict[int, np.ndarray]
) -> SpectrumSet:
    """Perform the single controlled interpolation allowed before demodulation."""
    previous_count = int(spectra.provenance.get("common_grid_resampling_count", 0))
    if previous_count != 0:
        raise ValueError("a spectrum may be resampled onto a common grid only once")
    channels: dict[str, SpectrumChannel] = {}
    for role, channel in spectra.channels.items():
        orders: list[np.ndarray] = []
        pixels: list[np.ndarray] = []
        wavelengths: list[np.ndarray] = []
        fluxes: list[np.ndarray] = []
        variances: list[np.ndarray] = []
        quality: list[np.ndarray] = []
        covariances: list[np.ndarray] = []
        for order in sorted(grids_by_order):
            selection = channel.order == order
            if not np.any(selection):
                raise ValueError(f"channel {role} has no samples for order {order}")
            grid = np.asarray(grids_by_order[order], dtype=np.float64)
            flux, variance, dq, covariance = _flux_conserving_resample(
                channel.wavelength[selection],
                channel.flux[selection],
                channel.variance[selection],
                channel.dq[selection],
                grid,
                (
                    channel.covariance_lag1[selection]
                    if channel.covariance_lag1 is not None
                    else None
                ),
            )
            orders.append(np.full(grid.shape, order, dtype=np.int32))
            pixels.append(np.arange(grid.size, dtype=np.float64))
            wavelengths.append(grid)
            fluxes.append(flux)
            variances.append(variance)
            quality.append(dq)
            covariances.append(covariance)
        channels[role] = SpectrumChannel(
            role=channel.role,
            order=np.concatenate(orders),
            pixel=np.concatenate(pixels),
            wavelength=np.concatenate(wavelengths),
            flux=np.concatenate(fluxes),
            variance=np.concatenate(variances),
            dq=np.concatenate(quality),
            covariance_lag1=np.concatenate(covariances),
            unit=channel.unit,
            wavelength_unit=channel.wavelength_unit,
            config_version=channel.config_version,
            provenance={
                **channel.provenance,
                "resampling": "flux-conserving-overlap-v1",
                "native_sample_count": int(channel.pixel.size),
            },
        )
    return SpectrumSet(
        channels=channels,
        native_grid=False,
        config_version=spectra.config_version,
        provenance={
            **spectra.provenance,
            "common_grid_resampling_count": 1,
            "resampling_algorithm": "flux-conserving-overlap-v1",
        },
    )


def logarithmic_air_grid(
    minimum_nm: float, maximum_nm: float, *, velocity_step_km_s: float = 1.8
) -> np.ndarray:
    if minimum_nm <= 0 or maximum_nm <= minimum_nm:
        raise ValueError("a positive increasing wavelength interval is required")
    ratio = np.exp(velocity_step_km_s / 299_792.458)
    size = int(np.floor(np.log(maximum_nm / minimum_nm) / np.log(ratio))) + 1
    return minimum_nm * ratio ** np.arange(size, dtype=np.float64)


def common_log_grids(
    spectra: list[SpectrumSet], *, velocity_step_km_s: float = 1.8
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    if not spectra:
        raise ValueError("at least one extracted spectrum is required")
    reference = next(iter(spectra[0].channels.values()))
    orders = sorted(int(value) for value in np.unique(reference.order))
    bounds: dict[int, tuple[float, float]] = {}
    for order in orders:
        minima: list[float] = []
        maxima: list[float] = []
        for spectrum in spectra:
            for channel in spectrum.channels.values():
                values = channel.wavelength[channel.order == order]
                values = values[np.isfinite(values)]
                if values.size < 2:
                    raise ValueError(f"order {order} lacks calibrated wavelength samples")
                minima.append(float(np.min(values)))
                maxima.append(float(np.max(values)))
        lower = max(minima)
        upper = min(maxima)
        if upper <= lower:
            raise ValueError(f"order {order} has no common wavelength coverage")
        bounds[order] = (lower, upper)
    global_grid = logarithmic_air_grid(
        min(lower for lower, _ in bounds.values()),
        max(upper for _, upper in bounds.values()),
        velocity_step_km_s=velocity_step_km_s,
    )
    grids = {
        order: global_grid[(global_grid >= lower) & (global_grid <= upper)]
        for order, (lower, upper) in bounds.items()
    }
    return global_grid, grids


def calibrate_simulated_thar(spectra: SpectrumSet) -> SpectrumSet:
    """Exercise the ThAr solution boundary and the one allowed common-grid resampling."""
    if not spectra.channels:
        raise ValueError("at least one extracted channel is required")
    reference = next(iter(spectra.channels.values()))
    order_ids = sorted(int(value) for value in np.unique(reference.order))
    configuration = default_instrument_configuration()
    line_count = int(configuration["spectrograph"]["simulated_thar_lines_per_order"])
    line_list: list[dict[str, float | int]] = []
    native_grids: dict[int, np.ndarray] = {}
    for order_index, order_id in enumerate(order_ids):
        pixels = reference.pixel[reference.order == order_id]
        if pixels.size < line_count:
            raise ValueError("the simulated detector is too small for the frozen ThAr line count")
        wavelengths = wavelength_grid(pixels.size, order_index, len(order_ids))
        sample_indices = np.unique(
            np.linspace(0, pixels.size - 1, line_count, dtype=np.int64)
        )
        for sample_index in sample_indices:
            line_list.append(
                {
                    "order": order_id,
                    "pixel": float(pixels[sample_index]),
                    "wavelength_nm": float(wavelengths[sample_index]),
                }
            )
        native_grids[order_id] = wavelengths
    solution = solve_wavelength(spectra, line_list)
    solution.wavelength_type = "UNVERIFIED_SIMULATED_THAR"
    solution.provenance.update(
        {
            "calibration": "SIMULATED_THAR",
            "line_count": len(line_list),
            "publication_allowed": False,
        }
    )
    calibrated = apply_wavelength_solution(spectra, solution)
    common_grids = {
        order: (wavelengths[:-1] + wavelengths[1:]) / 2.0
        for order, wavelengths in native_grids.items()
    }
    result = resample_common_grid(calibrated, common_grids)
    result.provenance.update(
        {
            "calibration": "SIMULATED_THAR",
            "wavelength_type": solution.wavelength_type,
            "publication_allowed": False,
        }
    )
    return result
