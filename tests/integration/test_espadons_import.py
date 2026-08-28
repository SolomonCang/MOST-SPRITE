from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient


def _write_group(directory: Path, *, first_id: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for sub_index in range(1, 5):
        values = np.pad(
            np.arange(1, 13, dtype=np.uint16).reshape(3, 4) + sub_index,
            ((0, 0), (0, 2)),
            constant_values=10,
        )
        values[:, 4:] = 10
        header = fits.Header(
            {
                "DETECTOR": "OLAPA",
                "OBSTYPE": "OBJECT",
                "OBJECT": "IMPORT TEST",
                "DATE-OBS": "2026-08-27",
                "UTC-OBS": f"01:0{sub_index}:00",
                "EXPTIME": 1.0,
                "CMMTSEQ": f"Q exposure {sub_index}, sequence 1",
                "DATASEC": "[1:4,1:3]",
                "BIASSEC": "[5:6,1:3]",
                "GAIN": 1.0,
                "RDNOISE": 2.0,
                "CCDBIN1": 1,
                "CCDBIN2": 1,
                "AMPLIST": "A",
                "EREADSPD": "SLOW",
            }
        )
        path = directory / f"{first_id + sub_index - 1}o.fits.fz"
        fits.HDUList(
            [fits.PrimaryHDU(), fits.CompImageHDU(values, header=header)]
        ).writeto(path)


def _write_calibration_frame(directory: Path, *, role: str, filename: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    values = np.arange(24, dtype=np.uint16).reshape(4, 6) + {
        "BIAS": 100,
        "FLAT": 1_000,
        "THAR": 10_000,
    }[role]
    header = fits.Header(
        {
            "DETECTOR": "OLAPA",
            "OBSTYPE": role,
            "OBJECT": role,
            "DATE-OBS": "2026-08-27",
            "UTC-OBS": "02:00:00",
            "DATASEC": "[1:4,1:4]",
            "BIASSEC": "[5:6,1:4]",
        }
    )
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(values, header=header)]).writeto(
        directory / filename
    )


@pytest.fixture
def import_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
    import_root = tmp_path / "import-root"
    _write_group(import_root / "clean", first_id=1000001)
    _write_group(import_root / "changed", first_id=2000001)
    outside = tmp_path / "outside"
    _write_group(outside, first_id=3000001)
    (import_root / "escape").symlink_to(outside, target_is_directory=True)

    monkeypatch.setenv("SPRITE_APP_ENV", "simulation")
    monkeypatch.setenv("SPRITE_AUTH_MODE", "dev")
    monkeypatch.setenv("SPRITE_LOCAL_AUTH_SECRET", "pytest-local-auth-key-2026-change-me")
    monkeypatch.setenv("SPRITE_ALLOW_LEGACY_DEV_HEADERS", "true")
    monkeypatch.setenv(
        "SPRITE_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'sprite-import.db'}"
    )
    monkeypatch.setenv("SPRITE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SPRITE_EMBEDDED_WORKERS", "false")
    monkeypatch.setenv("SPRITE_AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("SPRITE_IMPORT_ROOTS", json.dumps({"night": str(import_root)}))

    from most_sprite.config import get_settings
    from most_sprite.db.session import dispose_database

    get_settings.cache_clear()
    asyncio.run(dispose_database())

    from most_sprite.api.app import create_app

    with TestClient(create_app()) as client:
        yield client, import_root

    get_settings.cache_clear()
    asyncio.run(dispose_database())


def _headers(key: str, *, role: str = "data_reducer") -> dict[str, str]:
    return {
        "X-SPRITE-User": "import-test",
        "X-SPRITE-Role": role,
        "Idempotency-Key": key,
    }


def test_directory_inspection_and_import_are_secure_atomic_and_idempotent(
    import_api: tuple[TestClient, Path],
) -> None:
    client, _ = import_api
    inspected = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "clean", "instrument": "ESPADONS"},
        headers=_headers("inspect-clean-0001"),
    )
    assert inspected.status_code == 202, inspected.text
    inspection = inspected.json()
    assert inspection["status"] == "SUCCEEDED"
    assert len(inspection["inventory"]) == 4
    assert len(inspection["groups"]) == 1
    assert inspection["groups"][0]["sub_indices"] == [1, 2, 3, 4]
    assert len(inspection["manifest_sha256"]) == 64

    repeated_inspection = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "clean", "instrument": "ESPADONS"},
        headers=_headers("inspect-clean-0001"),
    )
    assert repeated_inspection.status_code == 202
    assert repeated_inspection.json()["id"] == inspection["id"]

    idempotency_conflict = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "changed", "instrument": "ESPADONS"},
        headers=_headers("inspect-clean-0001"),
    )
    assert idempotency_conflict.status_code == 409
    assert idempotency_conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

    imported = client.post(
        "/api/v1/imports",
        json={
            "inspection_id": inspection["id"],
            "manifest_sha256": inspection["manifest_sha256"],
        },
        headers=_headers("import-clean-0001"),
    )
    assert imported.status_code == 202, imported.text
    batch = imported.json()
    assert batch["status"] == "SUCCEEDED"
    assert len(batch["sequence_ids"]) == 1

    repeated_import = client.post(
        "/api/v1/imports",
        json={
            "inspection_id": inspection["id"],
            "manifest_sha256": inspection["manifest_sha256"],
        },
        headers=_headers("import-clean-0001"),
    )
    assert repeated_import.status_code == 202
    assert repeated_import.json()["id"] == batch["id"]

    products = client.get(
        f"/api/v1/products?sequence_id={batch['sequence_ids'][0]}",
        headers=_headers("read-products-0001", role="observer"),
    )
    assert products.status_code == 200
    l0_products = [item for item in products.json() if item["level"] == "L0"]
    assert len(l0_products) == 4
    assert all(item["instrument"] == "ESPADONS" for item in l0_products)
    assert all(item["qc_flag"] == "PASS" for item in l0_products)
    assert all("uri" not in item for item in l0_products)
    downloaded = client.get(
        l0_products[0]["download_url"],
        headers=_headers("download-product-0001", role="observer"),
    )
    assert downloaded.status_code == 200
    with fits.open(BytesIO(downloaded.content), checksum=True, memmap=False) as hdul:
        assert hdul[0].header["INSTRUME"] == "ESPADONS"
        assert hdul[0].header["DETECTOR"] == "OLAPA"
        assert hdul[0].header["SIMULATE"] is False


def test_every_mounted_detector_frame_role_has_an_image_preview(
    import_api: tuple[TestClient, Path],
) -> None:
    client, import_root = import_api
    preview_directory = import_root / "preview"
    _write_calibration_frame(preview_directory, role="BIAS", filename="biasb.fits.fz")
    _write_calibration_frame(preview_directory, role="FLAT", filename="flatf.fits.fz")
    _write_calibration_frame(preview_directory, role="THAR", filename="tharc.fits.fz")

    inspected = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "preview", "instrument": "ESPADONS"},
        headers=_headers("inspect-preview-0001"),
    )
    assert inspected.status_code == 202, inspected.text
    inspection = inspected.json()

    inventory_by_role = {item["role"]: item for item in inspection["inventory"]}
    assert set(inventory_by_role) == {"BIAS", "FLAT", "THAR"}
    for role in ("BIAS", "FLAT", "THAR"):
        preview = client.get(
            f"/api/v1/import-inspections/{inspection['id']}/preview",
            params={"relative_path": inventory_by_role[role]["relative_path"]},
            headers=_headers(f"preview-{role.lower()}-0001", role="observer"),
        )
        assert preview.status_code == 200, preview.text
        payload = preview.json()
        assert payload["role"] == role
        assert payload["shape"] == [4, 6]
        assert payload["preview_shape"] == [4, 6]
        assert len(payload["image"]) == 4

    missing = client.get(
        f"/api/v1/import-inspections/{inspection['id']}/preview",
        params={"relative_path": "preview/not-in-manifest.fits"},
        headers=_headers("preview-missing-0001", role="observer"),
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "IMPORT_ARTIFACT_NOT_FOUND"


@pytest.mark.parametrize("relative_path", ["../outside", "/tmp"])
def test_import_rejects_path_traversal_and_absolute_paths(
    import_api: tuple[TestClient, Path], relative_path: str
) -> None:
    client, _ = import_api
    response = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": relative_path},
        headers=_headers(f"forbidden-path-{relative_path.replace('/', '-')}-0001"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "IMPORT_PATH_FORBIDDEN"


def test_import_rejects_symlink_escape_and_changed_source(
    import_api: tuple[TestClient, Path],
) -> None:
    client, import_root = import_api
    escaped = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "escape"},
        headers=_headers("escape-inspection-0001"),
    )
    assert escaped.status_code == 422
    assert escaped.json()["code"] == "IMPORT_PATH_FORBIDDEN"

    inspected = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "changed"},
        headers=_headers("changed-inspection-0001"),
    ).json()
    changed_path = next((import_root / "changed").glob("*.fits.fz"))
    with changed_path.open("ab") as stream:
        stream.write(b"changed-after-inspection")
    imported = client.post(
        "/api/v1/imports",
        json={
            "inspection_id": inspected["id"],
            "manifest_sha256": inspected["manifest_sha256"],
        },
        headers=_headers("changed-import-0001"),
    )
    assert imported.status_code == 202
    assert imported.json()["status"] == "FAILED"
    assert imported.json()["error_code"] == "SOURCE_CHANGED"


def test_observer_cannot_inspect_or_commit_server_directories(
    import_api: tuple[TestClient, Path],
) -> None:
    client, _ = import_api
    response = client.post(
        "/api/v1/import-inspections",
        json={"root_id": "night", "relative_path": "clean"},
        headers=_headers("observer-inspection-0001", role="observer"),
    )
    assert response.status_code == 403
