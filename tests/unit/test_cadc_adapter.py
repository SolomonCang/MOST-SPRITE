from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.adapters.espadons import (
    GROUPS,
    adapt_reference_sign,
    group_for_product,
    normalized_residual_quantiles,
    robust_continuum_rms,
    wavelength_resolution_offsets,
)
from tools.testdata.fetch_cadc import load_manifest, validate_external_cache


def test_manifest_freezes_all_requested_artifacts() -> None:
    manifest = load_manifest(Path("tests/data-manifests/cadc-espadons-ad-leo-v1.yaml"))
    ids = {item["product_id"] for item in manifest["artifacts"]}
    assert len(ids) == 42
    assert {"1894668b", "1894682a", "1894876o", "1894887o"} <= ids
    assert {"1894876p", "1894880p", "1894884p"} <= ids


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
