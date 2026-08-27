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
from tools.testdata.fetch_cadc import load_manifest

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
            mask = np.asarray(bundle["mask"], dtype=bool)
            for field in ("polarization", "null1", "null2"):
                median, upper = normalized_residual_quantiles(
                    np.asarray(bundle[f"candidate_{field}"]),
                    np.asarray(bundle[f"reference_{field}"]),
                    np.asarray(bundle[f"comparison_uncertainty_{field}"]),
                    mask,
                )
                assert median <= 1.5, f"{stokes} {field} median residual {median}"
                assert upper <= 5.0, f"{stokes} {field} p99 residual {upper}"


def _read_l3_bundle(path: Path) -> dict[str, np.ndarray]:
    assert path.is_file(), f"missing L3 comparison bundle {path}"
    with np.load(path, allow_pickle=False) as bundle:
        return {name: np.asarray(bundle[name]) for name in bundle.files}


def _assert_l3_residual_contract(
    label: str,
    bundle: dict[str, np.ndarray],
) -> None:
    mask = np.asarray(bundle["mask"], dtype=bool)
    for field in ("polarization", "null1", "null2"):
        median, upper = normalized_residual_quantiles(
            bundle[f"candidate_{field}"],
            bundle[f"reference_{field}"],
            bundle[f"comparison_uncertainty_{field}"],
            mask,
        )
        assert median <= 1.5, f"{label} {field} median residual {median}"
        assert upper <= 5.0, f"{label} {field} p99 residual {upper}"


def test_hr_5501_non_polarized_standard(candidate_root: Path) -> None:
    bundle = _read_l3_bundle(candidate_root / "l3" / "HR_5501_V.npz")
    _assert_l3_residual_contract("HR 5501 V", bundle)
    mask = np.asarray(bundle["mask"], dtype=bool)
    valid = mask & np.isfinite(bundle["raw_candidate_polarization"])
    assert np.count_nonzero(valid) > 0
    pseudo_polarization = abs(float(np.median(bundle["raw_candidate_polarization"][valid])))
    assert pseudo_polarization <= 1e-3
    zeros = np.zeros_like(bundle["reference_uncertainty"])
    for field in ("null1", "null2"):
        median, upper = normalized_residual_quantiles(
            bundle[f"candidate_{field}"],
            zeros,
            bundle[f"candidate_uncertainty_{field}"],
            mask,
        )
        assert median <= 1.5, f"HR 5501 {field} noise median {median}"
        assert upper <= 5.0, f"HR 5501 {field} noise p99 {upper}"


def test_hd_236928_linear_standard_sign_structure_and_angle(
    candidate_root: Path,
) -> None:
    q_bundle = _read_l3_bundle(candidate_root / "l3" / "HD_236928_Q.npz")
    u_bundle = _read_l3_bundle(candidate_root / "l3" / "HD_236928_U.npz")
    _assert_l3_residual_contract("HD 236928 Q", q_bundle)
    _assert_l3_residual_contract("HD 236928 U", u_bundle)

    q_candidate = float(q_bundle["r_band_median"])
    u_candidate = float(u_bundle["r_band_median"])
    manifest = load_manifest(Path("tests/data-manifests/cadc-espadons-hd-236928-v1.yaml"))
    standard = manifest["freeze"]["polarization_standard"]
    reference_angle_deg = float(standard["position_angle_deg"])
    reference_amplitude = float(standard["degree_percent"]) / 100.0
    angle_rad = np.deg2rad(2.0 * reference_angle_deg)
    q_reference = reference_amplitude * np.cos(angle_rad)
    u_reference = reference_amplitude * np.sin(angle_rad)

    assert np.sign(q_candidate) == np.sign(q_reference)
    assert np.sign(u_candidate) == np.sign(u_reference)
    assert 0.03 <= np.hypot(q_candidate, u_candidate) <= 0.10
    candidate_angle_deg = float(np.rad2deg(0.5 * np.arctan2(u_candidate, q_candidate)) % 180.0)
    angle_delta_deg = abs((candidate_angle_deg - reference_angle_deg + 90.0) % 180.0 - 90.0)
    # This is a sign/angle sentinel, not a claim of absolute continuum
    # polarimetry.  ESPaDOnS continuum systematics are much larger than the
    # catalog uncertainty, so the release gate deliberately uses 2 degrees.
    assert angle_delta_deg <= 2.0
