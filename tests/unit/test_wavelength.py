from __future__ import annotations

import numpy as np
import pytest
from most_sprite.pipeline.echelle.models import SpectrumChannel, SpectrumSet
from most_sprite.pipeline.echelle.wlcalib import solve_wavelength
from most_sprite.pipeline.wavelength import apply_wavelength_solution, resample_common_grid


def native_spectrum() -> SpectrumSet:
    pixel = np.arange(6, dtype=np.float64)
    channel = SpectrumChannel(
        role="O_BEAM",
        order=np.full(6, 57, dtype=np.int32),
        pixel=pixel,
        wavelength=np.full(6, np.nan),
        flux=2.0 * pixel + 1.0,
        variance=np.full(6, 4.0),
        dq=np.zeros(6, dtype=np.uint32),
        config_version="simulation-v1",
    )
    return SpectrumSet(
        channels={"O_BEAM": channel},
        config_version="simulation-v1",
        provenance={"common_grid_resampling_count": 0},
    )


def test_thar_solution_and_single_common_grid_resampling() -> None:
    native = native_spectrum()
    solution = solve_wavelength(
        native,
        [
            {"order": 57, "pixel": 0.0, "wavelength_nm": 500.0},
            {"order": 57, "pixel": 2.0, "wavelength_nm": 500.2},
            {"order": 57, "pixel": 5.0, "wavelength_nm": 500.5},
        ],
    )
    calibrated = apply_wavelength_solution(native, solution)
    assert np.allclose(calibrated.channels["O_BEAM"].wavelength, 500.0 + 0.1 * np.arange(6))

    grid = np.array([500.05, 500.15, 500.25, 500.35, 500.45])
    resampled = resample_common_grid(calibrated, {57: grid})
    assert resampled.provenance["common_grid_resampling_count"] == 1
    assert not resampled.native_grid
    assert np.allclose(resampled.channels["O_BEAM"].variance, 2.0)
    with pytest.raises(ValueError, match="only once"):
        resample_common_grid(resampled, {57: grid})
