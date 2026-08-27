from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from tests.adapters.espadons import (
    GROUPS,
    STANDARD_GROUPS,
    read_intensity_reference,
    read_polarization_reference,
)
from tools.testdata.fetch_cadc import (
    artifact_path,
    load_manifest,
    validate_external_cache,
    verify_artifact,
)

pytestmark = pytest.mark.golden

STANDARD_MANIFESTS = (
    Path("tests/data-manifests/cadc-espadons-hr-5501-v1.yaml"),
    Path("tests/data-manifests/cadc-espadons-hd-236928-v1.yaml"),
)


@pytest.fixture(scope="module")
def frozen_data() -> tuple[Path, dict, dict[str, dict]]:
    value = os.environ.get("SPRITE_TESTDATA_DIR")
    if not value:
        pytest.skip("SPRITE_TESTDATA_DIR is required for the cached CADC regression")
    cache = validate_external_cache(Path(value))
    manifest = load_manifest(Path("tests/data-manifests/cadc-espadons-ad-leo-v1.yaml"))
    artifacts = {item["product_id"]: item for item in manifest["artifacts"]}
    for artifact in artifacts.values():
        verify_artifact(
            artifact_path(cache, manifest["manifest_id"], artifact),
            artifact,
        )
    return cache, manifest, artifacts


@pytest.fixture(scope="module")
def standard_data() -> tuple[Path, dict[str, tuple[dict, dict[str, dict]]]]:
    value = os.environ.get("SPRITE_TESTDATA_DIR")
    if not value:
        pytest.skip("SPRITE_TESTDATA_DIR is required for the cached CADC regression")
    cache = validate_external_cache(Path(value))
    datasets: dict[str, tuple[dict, dict[str, dict]]] = {}
    for path in STANDARD_MANIFESTS:
        manifest = load_manifest(path)
        artifacts = {item["product_id"]: item for item in manifest["artifacts"]}
        for artifact in artifacts.values():
            verify_artifact(
                artifact_path(cache, manifest["manifest_id"], artifact),
                artifact,
            )
        datasets[manifest["manifest_id"]] = (manifest, artifacts)
    return cache, datasets


def test_raw_detector_and_reference_metadata(frozen_data) -> None:  # noqa: ANN001
    cache, manifest, artifacts = frozen_data
    for group in GROUPS.values():
        for product_id in group.raw_product_ids:
            path = artifact_path(cache, manifest["manifest_id"], artifacts[product_id])
            with fits.open(path, memmap=False) as hdul:
                assert hdul[1].data.shape == (4640, 2080)
                assert hdul[1].header["OBJECT"].strip() == "AD Leo"
                assert "Polarimetry" in hdul[1].header["INSTMODE"]
        for product_id in group.intensity_product_ids:
            path = artifact_path(cache, manifest["manifest_id"], artifacts[product_id])
            reference = read_intensity_reference(path)
            wavelength_steps = np.diff(reference.wavelength_nm)
            order_boundaries = np.flatnonzero(wavelength_steps < 0) + 1
            assert order_boundaries.size >= 30
            for order_wave in np.split(reference.wavelength_nm, order_boundaries):
                assert np.all(np.diff(order_wave) > 0)
            assert reference.provenance["production_mapping_affected"] is False


def test_q_u_v_reference_sign_and_group_sources(frozen_data) -> None:  # noqa: ANN001
    cache, manifest, artifacts = frozen_data
    for stokes, group in GROUPS.items():
        path = artifact_path(
            cache,
            manifest["manifest_id"],
            artifacts[group.polarization_product_id],
        )
        reference = read_polarization_reference(path)
        assert reference.provenance["stokes"] == stokes
        assert reference.provenance["source_raw_product_ids"] == list(group.raw_product_ids)
        assert reference.provenance["production_mapping_affected"] is False


def test_standard_star_headers_and_reference_sources(standard_data) -> None:  # noqa: ANN001
    cache, datasets = standard_data
    expected_object = {
        "HR_5501_V": "HR 5501",
        "HD_236928_Q": "HD 236928",
        "HD_236928_U": "HD 236928",
    }
    for name, group in STANDARD_GROUPS.items():
        manifest_id = (
            "cadc-espadons-hr-5501-v1"
            if name.startswith("HR_")
            else "cadc-espadons-hd-236928-v1"
        )
        manifest, artifacts = datasets[manifest_id]
        for sub_index, product_id in enumerate(group.raw_product_ids, start=1):
            path = artifact_path(cache, manifest["manifest_id"], artifacts[product_id])
            with fits.open(path, memmap=False) as hdul:
                assert list(hdul[1].data.shape) == manifest["freeze"]["raw_image_shape"]
                header = hdul[1].header
                assert header["OBJECT"].strip() == expected_object[name]
                assert header["DETECTOR"].strip() == "OLAPA"
                assert header["DATASEC"].strip() == manifest["freeze"]["data_section"]
                assert header["INSTMODE"].strip() == "Polarimetry, R=65,000"
                assert header["CMMTSEQ"].strip().startswith(
                    f"{group.stokes} exposure {sub_index}"
                )
        path = artifact_path(
            cache,
            manifest["manifest_id"],
            artifacts[group.polarization_product_id],
        )
        reference = read_polarization_reference(path)
        assert reference.provenance["stokes"] == group.stokes
        assert reference.provenance["source_raw_product_ids"] == list(
            group.raw_product_ids
        )
        assert reference.provenance["sign_multiplier"] == group.reference_sign
        assert reference.provenance["production_mapping_affected"] is False
        if name == "HR_5501_V":
            valid = (
                np.isfinite(reference.polarization)
                & np.isfinite(reference.uncertainty)
                & (reference.uncertainty > 0)
            )
            assert abs(float(np.median(reference.polarization[valid]))) <= 1e-3
            for null in (reference.null1, reference.null2):
                noise_residual = np.abs(null[valid] / reference.uncertainty[valid])
                assert float(np.median(noise_residual)) <= 1.5
                assert float(np.quantile(noise_residual, 0.99)) <= 5.0
