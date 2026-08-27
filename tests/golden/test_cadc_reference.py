from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from tests.adapters.espadons import (
    GROUPS,
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
            assert np.all(np.diff(reference.wavelength_nm) >= 0)
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
