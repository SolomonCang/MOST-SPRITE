from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from tests.adapters.espadons import (
    GROUPS,
    normalized_residual_quantiles,
    robust_continuum_rms,
    wavelength_resolution_offsets,
)

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def candidate_root() -> Path:
    value = os.environ.get("SPRITE_CADC_CANDIDATE_DIR")
    if not value:
        pytest.skip("SPRITE_CADC_CANDIDATE_DIR is required for numerical CADC comparison")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        pytest.fail(f"candidate regression bundle does not exist: {path}")
    return path


def test_l2_wavelength_and_continuum_thresholds(candidate_root: Path) -> None:
    for group in GROUPS.values():
        for product_id in group.raw_product_ids:
            path = candidate_root / "l2" / f"{product_id}.npz"
            assert path.is_file(), f"missing L2 comparison bundle {path}"
            with np.load(path, allow_pickle=False) as bundle:
                candidate_wave = np.asarray(bundle["candidate_wavelength_nm"])
                reference_wave = np.asarray(bundle["reference_wavelength_nm"])
                candidate_flux = np.asarray(bundle["candidate_flux"])
                reference_flux = np.asarray(bundle["reference_flux"])
                mask = np.asarray(bundle["continuum_mask"], dtype=bool)
            offsets = wavelength_resolution_offsets(candidate_wave, reference_wave)
            assert float(np.median(offsets[mask])) < 0.1
            assert robust_continuum_rms(candidate_flux, reference_flux, mask) < 0.03


def test_l3_polarization_and_null_thresholds(candidate_root: Path) -> None:
    for stokes in GROUPS:
        path = candidate_root / "l3" / f"{stokes}.npz"
        assert path.is_file(), f"missing L3 comparison bundle {path}"
        with np.load(path, allow_pickle=False) as bundle:
            uncertainty = np.asarray(bundle["reference_uncertainty"])
            mask = np.asarray(bundle["mask"], dtype=bool)
            for field in ("polarization", "null1", "null2"):
                median, upper = normalized_residual_quantiles(
                    np.asarray(bundle[f"candidate_{field}"]),
                    np.asarray(bundle[f"reference_{field}"]),
                    uncertainty,
                    mask,
                )
                assert median <= 1.5, f"{stokes} {field} median residual {median}"
                assert upper <= 5.0, f"{stokes} {field} p99 residual {upper}"
