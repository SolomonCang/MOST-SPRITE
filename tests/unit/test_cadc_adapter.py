from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.adapters.espadons import (
    GROUPS,
    STANDARD_GROUPS,
    PolarizationReference,
    adapt_reference_sign,
    group_for_product,
    match_spectral_line_continuum,
    merge_polarization_reference,
    normalized_residual_quantiles,
    robust_continuum_rms,
    wavelength_resolution_offsets,
)
from tools.testdata.fetch_cadc import load_manifest, validate_external_cache


def test_manifests_freeze_all_requested_artifacts() -> None:
    ad_leo = load_manifest(Path("tests/data-manifests/cadc-espadons-ad-leo-v1.yaml"))
    ad_leo_ids = {item["product_id"] for item in ad_leo["artifacts"]}
    assert len(ad_leo_ids) == 42
    assert {"1894668b", "1894682a", "1894876o", "1894887o"} <= ad_leo_ids
    assert {"1894876p", "1894880p", "1894884p"} <= ad_leo_ids

    hr_5501 = load_manifest(Path("tests/data-manifests/cadc-espadons-hr-5501-v1.yaml"))
    hr_ids = {item["product_id"] for item in hr_5501["artifacts"]}
    assert len(hr_ids) == 30
    assert {"3210538b", "3210561a", "3210562c"} <= hr_ids
    assert {"3210588o", "3210591o", "3210588p"} <= hr_ids
    assert hr_5501["freeze"]["detector"] == "OLAPA"
    assert hr_5501["freeze"]["raw_image_shape"] == [4608, 2088]
    assert hr_5501["freeze"]["instrument_mode"] == "Polarimetry, R=65,000"
    assert hr_5501["freeze"]["readout_mode"].startswith("Normal:")

    hd_236928 = load_manifest(Path("tests/data-manifests/cadc-espadons-hd-236928-v1.yaml"))
    hd_ids = {item["product_id"] for item in hd_236928["artifacts"]}
    assert len(hd_ids) == 35
    assert {"3252040b", "3252063a", "3252064c"} <= hd_ids
    assert {"3251968o", "3251975o", "3251968p", "3251972p"} <= hd_ids
    assert hd_236928["freeze"]["readout_mode"].startswith("Normal:")
    assert hd_236928["freeze"]["data_section"] == "[21:2068,1:4608]"
    standard = hd_236928["freeze"]["polarization_standard"]
    assert standard["alias"] == "BD+59 389"
    assert standard["position_angle_deg"] == pytest.approx(98.14)


def test_espadons_u_sign_conversion_is_explicit_and_test_only() -> None:
    values = np.array([0.1, -0.2])
    polarization, null1, null2, provenance = adapt_reference_sign(
        "U", values, values / 2, values / 4
    )
    assert np.array_equal(polarization, -values)
    assert np.array_equal(null1, -values / 2)
    assert np.array_equal(null2, -values / 4)
    assert provenance["production_mapping_affected"] is False
    assert GROUPS["Q"].reference_sign == GROUPS["V"].reference_sign == 1
    assert group_for_product("1894886o").stokes == "U"


def test_standard_star_groups_follow_fits_header_stokes() -> None:
    assert STANDARD_GROUPS["HR_5501_V"].stokes == "V"
    assert group_for_product("3210588o") == STANDARD_GROUPS["HR_5501_V"]
    assert group_for_product("3251968p") == STANDARD_GROUPS["HD_236928_Q"]
    assert group_for_product("3251975o") == STANDARD_GROUPS["HD_236928_U"]
    assert STANDARD_GROUPS["HD_236928_U"].reference_sign == -1


def test_downloader_rejects_repository_local_cache() -> None:
    with pytest.raises(ValueError, match="outside"):
        validate_external_cache(Path(".cache/cadc"))


def test_frozen_regression_statistics() -> None:
    wavelength = np.linspace(500.0, 501.0, 100)
    offset = wavelength + 0.05 * wavelength / 65_000.0
    assert np.median(wavelength_resolution_offsets(offset, wavelength)) == pytest.approx(0.05)
    reference = 1.0 + 0.02 * np.sin(np.linspace(0, 2 * np.pi, 100))
    candidate = reference * 1.01
    mask = np.ones(100, dtype=bool)
    assert robust_continuum_rms(candidate, reference, mask) == pytest.approx(0.01)
    uncertainty = np.full(100, 0.001)
    median, upper = normalized_residual_quantiles(reference + 0.001, reference, uncertainty, mask)
    assert median == pytest.approx(1.0)
    assert upper == pytest.approx(1.0)


def test_reference_orders_are_merged_independently_for_comparison() -> None:
    reference = PolarizationReference(
        wavelength_nm=np.array([500.0, 500.01, 500.02, 500.01, 500.02, 500.03]),
        intensity=np.ones(6),
        polarization=np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        null1=np.zeros(6),
        null2=np.zeros(6),
        uncertainty=np.ones(6),
        provenance={},
    )
    merged = merge_polarization_reference(
        reference, np.array([500.0, 500.01, 500.02, 500.03])
    )
    assert np.allclose(merged.polarization, [1.0, 3.0, 4.0, 6.0])
    assert merged.uncertainty[1] == pytest.approx(1.0 / np.sqrt(2.0))


def test_reference_order_split_recognizes_large_positive_boundary_jump() -> None:
    reference = PolarizationReference(
        wavelength_nm=np.array([500.0, 500.01, 500.02, 501.0, 501.01, 501.02]),
        intensity=np.ones(6),
        polarization=np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0]),
        null1=np.zeros(6),
        null2=np.zeros(6),
        uncertainty=np.ones(6),
        provenance={},
    )
    merged = merge_polarization_reference(
        reference,
        np.array([500.0, 500.01, 500.02, 500.5, 501.0, 501.01, 501.02]),
    )

    assert np.allclose(merged.polarization[[0, 1, 2, 4, 5, 6]], [1, 2, 3, 10, 20, 30])
    assert np.isnan(merged.polarization[3])


def test_line_comparison_removes_only_smooth_candidate_offset() -> None:
    wavelength = np.linspace(500.0, 502.0, 200)
    reference = 0.01 * np.exp(-0.5 * np.square((wavelength - 501.0) / 0.02))
    candidate = reference + 0.05 + 0.002 * (wavelength - 501.0)
    matched = match_spectral_line_continuum(
        wavelength,
        candidate,
        reference,
        np.ones(wavelength.shape, dtype=bool),
    )
    assert np.max(np.abs(matched - reference)) < 6e-4
