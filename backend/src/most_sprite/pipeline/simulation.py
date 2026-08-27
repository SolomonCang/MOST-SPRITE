from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from most_sprite.domain.enums import DataMode


def _simulation_configuration() -> dict:
    # Local import avoids coupling the versioned configuration loader to this
    # synthetic-data helper during module initialization.
    from most_sprite.configuration import default_instrument_configuration

    return default_instrument_configuration()


def channel_roles(mode: DataMode) -> tuple[str, ...]:
    if mode.is_polarimetric:
        return ("O_BEAM", "E_BEAM")
    return ("TARGET", "SKY", "DISABLED")


def channel_centers(
    rows: int, mode: DataMode, n_orders: int | None = None
) -> dict[str, NDArray[np.float64]]:
    if n_orders is None:
        n_orders = int(_simulation_configuration()["spectrograph"]["simulation_order_count"])
    roles = channel_roles(mode)
    margin = max(6.0, rows * 0.06)
    all_centers = np.linspace(margin, rows - margin, n_orders * len(roles), dtype=np.float64)
    matrix = all_centers.reshape(n_orders, len(roles))
    return {role: matrix[:, index] for index, role in enumerate(roles)}


def base_spectrum(columns: int, order_index: int) -> NDArray[np.float64]:
    x = np.linspace(0.0, 1.0, columns, dtype=np.float64)
    continuum = 1.0 + 0.08 * np.sin(2 * np.pi * (x + order_index / 7))
    line_a = 0.28 * np.exp(-0.5 * ((x - (0.24 + 0.025 * order_index)) / 0.018) ** 2)
    line_b = 0.18 * np.exp(-0.5 * ((x - (0.66 - 0.015 * order_index)) / 0.025) ** 2)
    return np.clip(continuum - line_a - line_b, 0.05, None)


def wavelength_grid(
    columns: int, order_index: int, n_orders: int | None = None
) -> NDArray[np.float64]:
    configuration = _simulation_configuration()
    if n_orders is None:
        n_orders = int(configuration["spectrograph"]["simulation_order_count"])
    lower, upper = (float(value) for value in configuration["wavelength"]["simulation_range_nm"])
    edges = np.linspace(lower, upper, n_orders + 1)
    return np.linspace(edges[order_index], edges[order_index + 1], columns, endpoint=False)
