from __future__ import annotations

import asyncio
import time
from io import BytesIO
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient


def wait_for(
    client: TestClient,
    path: str,
    headers: dict[str, str],
    predicate,
    *,
    timeout: float = 20.0,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if predicate(last):
            return last
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {path}; last value: {last}")


@pytest.mark.parametrize(
    ("mode", "expected_exposures", "expected_l3_columns"),
    [
        ("POL_Q", 4, {"I", "P", "N1", "N2", "DQ"}),
        ("NONPOL", 1, {"TARGET", "SKY", "ALPHA", "I", "DQ"}),
    ],
)
def test_simulated_sequence_reaches_l3(
    api_client: TestClient,
    observer_headers: dict[str, str],
    mode: str,
    expected_exposures: int,
    expected_l3_columns: set[str],
) -> None:
    payload = {"target_name": f"SIM-{mode}", "mode": mode, "exposure_time": 0.1, "repeats": 1}
    validation = api_client.post("/api/v1/sequences:validate", json=payload)
    assert validation.status_code == 200
    assert validation.json()["estimated_exposures"] == expected_exposures
    assert validation.json()["issues"][0]["code"] == "UNVERIFIED_CONFIGURATION"

    create_headers = observer_headers | {"Idempotency-Key": f"create-{mode}-{uuid4()}"}
    created = api_client.post("/api/v1/sequences", json=payload, headers=create_headers)
    assert created.status_code == 202, created.text
    sequence_id = created.json()["resource_id"]

    repeated = api_client.post("/api/v1/sequences", json=payload, headers=create_headers)
    assert repeated.status_code == 202
    assert repeated.json() == created.json()

    started = api_client.post(
        f"/api/v1/sequences/{sequence_id}:start",
        headers=observer_headers | {"Idempotency-Key": f"start-{sequence_id}"},
    )
    assert started.status_code == 202, started.text
    action_command_id = started.json()["command_id"]

    sequence = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] in {"SUCCEEDED", "FAILED"},
    )
    assert sequence["status"] == "SUCCEEDED", sequence
    assert sequence["completed_exposures"] == expected_exposures
    action_command = wait_for(
        api_client,
        f"/api/v1/commands/{action_command_id}",
        observer_headers,
        lambda value: value["status"] == "SUCCEEDED",
    )
    assert action_command["command_type"] == "START"

    exposures = api_client.get(
        f"/api/v1/sequences/{sequence_id}/exposures", headers=observer_headers
    ).json()
    assert len(exposures) == expected_exposures
    assert all(item["status"] == "COMMITTED" for item in exposures)
    if mode == "POL_Q":
        assert [(item["fr1_commanded"], item["fr3_commanded"]) for item in exposures] == [
            (0.0, 0.0),
            (45.0, 90.0),
            (90.0, 45.0),
            (135.0, 135.0),
        ]

    products = wait_for(
        api_client,
        f"/api/v1/products?sequence_id={sequence_id}",
        observer_headers,
        lambda values: any(item["level"] == "L3" for item in values),
    )
    levels = {item["level"] for item in products}
    assert levels >= {"L0", "QUICKLOOK", "L1", "L2", "L3"}
    l0 = [item for item in products if item["level"] == "L0"]
    assert len(l0) == expected_exposures
    assert all(item["qc_flag"] == "SIMULATION_ONLY" for item in products)
    l0_preview = api_client.get(
        f"/api/v1/products/{l0[0]['id']}/preview", headers=observer_headers
    )
    assert l0_preview.status_code == 200, l0_preview.text
    assert l0_preview.json()["shape"]
    assert l0_preview.json()["image"]
    assert l0_preview.json()["preview_reducer"] == "finite-max-pool-v1"
    assert l0_preview.json()["preview_shape"] == [
        len(l0_preview.json()["image"]),
        len(l0_preview.json()["image"][0]),
    ]
    assert len(l0_preview.json()["image"]) <= 384
    assert len(l0_preview.json()["image"][0]) <= 768

    l2 = next(item for item in products if item["level"] == "L2")
    assert "uri" not in l2
    downloaded = api_client.get(l2["download_url"], headers=observer_headers)
    assert downloaded.status_code == 200
    with fits.open(BytesIO(downloaded.content), checksum=True, memmap=False) as hdul:
        assert hdul[0].header["RESAMPN"] == 1
        channel_hdus = [hdu for hdu in hdul[1:] if hdu.header.get("CHANNEL_ROLE")]
        assert channel_hdus
        assert all(np.all(np.isfinite(hdu.data["WAVE"])) for hdu in channel_hdus)

    l3 = next(item for item in products if item["level"] == "L3")
    preview = api_client.get(f"/api/v1/products/{l3['id']}/preview", headers=observer_headers)
    assert preview.status_code == 200, preview.text
    assert set(preview.json()["columns"]) >= expected_l3_columns

    qc = api_client.get(f"/api/v1/products/{l3['id']}/qc", headers=observer_headers)
    assert qc.status_code == 200
    assert qc.json()
    assert all(item["reason_code"] for item in qc.json())

    lineage = api_client.get(f"/api/v1/products/{l3['id']}/lineage", headers=observer_headers)
    assert lineage.status_code == 200
    lineage_levels = {item["level"] for item in lineage.json()["nodes"]}
    assert lineage_levels >= {"L0", "L1", "L2", "L3"}
    assert lineage.json()["edges"]

    runs = api_client.get("/api/v1/processing-runs", headers=observer_headers).json()
    run = next(item for item in runs if item["sequence_id"] == sequence_id)
    assert run["status"] == "SUCCEEDED"
    assert run["progress"] == 1.0
    assert all(len(run[field]) == 64 for field in (
        "input_hash",
        "calibration_hash",
        "parameter_hash",
        "code_hash",
    ))
    stages_response = api_client.get(
        f"/api/v1/processing-runs/{run['id']}/stages", headers=observer_headers
    )
    assert stages_response.status_code == 200, stages_response.text
    stages = stages_response.json()
    assert [stage["key"] for stage in stages] == ["l0", "quicklook", "l1", "l2", "l3"]
    assert [stage["level"] for stage in stages] == ["L0", "QUICKLOOK", "L1", "L2", "L3"]
    assert all(stage["status"] == "AVAILABLE" for stage in stages)
    assert all(stage["products"] for stage in stages)
    assert next(stage for stage in stages if stage["key"] == "l1")[
        "expected_output_count"
    ] == expected_exposures
    assert next(stage for stage in stages if stage["key"] == "l3")[
        "expected_output_count"
    ] == (1 if mode == "POL_Q" else expected_exposures)

    reducer_headers = {
        "X-SPRITE-User": "test-reducer",
        "X-SPRITE-Role": "data_reducer",
    }
    first_key = f"run-a-{sequence_id}"
    first_profile = api_client.post(
        "/api/v1/processing-runs",
        json={"sequence_id": sequence_id, "parameters": {"profile": "regression-A"}},
        headers=reducer_headers | {"Idempotency-Key": first_key},
    )
    same_key_profile = api_client.post(
        "/api/v1/processing-runs",
        json={"sequence_id": sequence_id, "parameters": {"profile": "regression-A"}},
        headers=reducer_headers | {"Idempotency-Key": first_key},
    )
    conflicting_profile = api_client.post(
        "/api/v1/processing-runs",
        json={"sequence_id": sequence_id, "parameters": {"profile": "conflict"}},
        headers=reducer_headers | {"Idempotency-Key": first_key},
    )
    repeated_profile = api_client.post(
        "/api/v1/processing-runs",
        json={"sequence_id": sequence_id, "parameters": {"profile": "regression-A"}},
        headers=reducer_headers | {"Idempotency-Key": f"run-a-repeat-{sequence_id}"},
    )
    second_profile = api_client.post(
        "/api/v1/processing-runs",
        json={"sequence_id": sequence_id, "parameters": {"profile": "regression-B"}},
        headers=reducer_headers | {"Idempotency-Key": f"run-b-{sequence_id}"},
    )
    assert {
        first_profile.status_code,
        same_key_profile.status_code,
        repeated_profile.status_code,
        second_profile.status_code,
    } == {202}
    assert same_key_profile.json() == first_profile.json()
    assert conflicting_profile.status_code == 409
    assert conflicting_profile.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert first_profile.json()["processing_run_id"] == repeated_profile.json()["processing_run_id"]
    assert first_profile.json()["processing_run_id"] != second_profile.json()["processing_run_id"]
    for response in (first_profile, second_profile):
        run_id = response.json()["processing_run_id"]
        completed_run = wait_for(
            api_client,
            f"/api/v1/processing-runs/{run_id}",
            reducer_headers,
            lambda value: value["status"] == "SUCCEEDED",
        )
        assert completed_run["progress"] == 1.0


def test_error_contract_and_role_enforcement(
    api_client: TestClient, observer_headers: dict[str, str]
) -> None:
    payload = {"target_name": "SIM", "mode": "NONPOL", "exposure_time": 0.1}
    no_key = api_client.post("/api/v1/sequences", json=payload, headers=observer_headers)
    assert no_key.status_code == 422
    assert set(no_key.json()) == {"code", "message", "details", "correlation_id", "retryable"}

    forbidden = api_client.post(
        "/api/v1/calibrations",
        json={"calibration_type": "BIAS", "uri": "/external/bias.fits", "checksum": "abc"},
        headers=observer_headers | {"Idempotency-Key": "calibration-test"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"


def test_calibration_approval_and_publication_gates_are_idempotent(
    api_client: TestClient,
    observer_headers: dict[str, str],
) -> None:
    payload = {
        "target_name": "PUBLICATION-GATES",
        "mode": "NONPOL",
        "exposure_time": 0.1,
    }
    created = api_client.post(
        "/api/v1/sequences",
        json=payload,
        headers=observer_headers | {"Idempotency-Key": "publication-sequence-0001"},
    )
    sequence_id = created.json()["resource_id"]
    api_client.post(
        f"/api/v1/sequences/{sequence_id}:start",
        headers=observer_headers | {"Idempotency-Key": "publication-start-0001"},
    )
    products = wait_for(
        api_client,
        f"/api/v1/products?sequence_id={sequence_id}",
        observer_headers,
        lambda values: any(item["level"] == "L3" for item in values),
    )
    l3 = next(item for item in products if item["level"] == "L3")
    simulation_l2 = next(item for item in products if item["level"] == "L2")

    async def attach_real_authority() -> str:
        from most_sprite.db.models import (
            CalibrationRun,
            CalibrationSet,
            ImportBatch,
            ImportInspection,
            Product,
        )
        from most_sprite.db.session import session_scope

        async with session_scope() as session:
            inspection = ImportInspection(
                idempotency_key="publication-inspection-0001",
                root_id="test",
                relative_path="publication",
                instrument="ESPADONS",
                status="SUCCEEDED",
                manifest_sha256="a" * 64,
                inventory_json=[],
                groups_json=[],
                calibration_summary_json={},
                warnings_json=[],
                created_by="test-reducer",
            )
            session.add(inspection)
            await session.flush()
            batch = ImportBatch(
                inspection_id=inspection.id,
                idempotency_key="publication-import-0001",
                manifest_sha256="a" * 64,
                status="SUCCEEDED",
                sequence_ids_json=[sequence_id],
                created_by="test-reducer",
            )
            session.add(batch)
            await session.flush()
            run = CalibrationRun(
                import_batch_id=batch.id,
                idempotency_key="publication-calibration-0001",
                status="SUCCEEDED",
                progress=1.0,
                parameter_version="espadons-olapa-v1",
                created_by="test-reducer",
            )
            session.add(run)
            await session.flush()
            calibration_set = CalibrationSet(
                calibration_run_id=run.id,
                import_batch_id=batch.id,
                instrument="ESPADONS",
                detector="OLAPA",
                observing_night="2026-08-27",
                readout_mode="1|1|a,b|Normal",
                status="UNVERIFIED",
                calibration_hash="c" * 64,
                artifact_uri="/managed/calibration-set.fits",
                qc_flag="WARNING",
                qc_json={"passed": True},
                warnings_json=[{"code": "FLAT_COUNT_BELOW_RECOMMENDED"}],
            )
            session.add(calibration_set)
            await session.flush()
            product = await session.get(Product, l3["id"])
            assert product is not None
            product.instrument = "ESPADONS"
            product.detector_profile = "OLAPA"
            product.import_batch_id = batch.id
            product.calibration_set_id = calibration_set.id
            product.qc_flag = "WARNING"
            product.metadata_json = {
                **product.metadata_json,
                "simulation_only": False,
            }
            return calibration_set.id

    calibration_set_id = asyncio.run(attach_real_authority())
    admin = {
        "X-SPRITE-User": "test-admin",
        "X-SPRITE-Role": "administrator",
    }
    approval_path = f"/api/v1/calibration-sets/{calibration_set_id}/approve"
    warning_rejected = api_client.post(
        approval_path,
        json={"reason": "science review completed", "accept_warnings": False},
        headers=admin | {"Idempotency-Key": "approve-warning-0001"},
    )
    assert warning_rejected.status_code == 409
    assert warning_rejected.json()["code"] == "CALIBRATION_WARNING_ACCEPTANCE_REQUIRED"

    approval_body = {
        "reason": "science review completed",
        "accept_warnings": True,
    }
    approval_headers = admin | {"Idempotency-Key": "approve-calset-0001"}
    approved = api_client.post(
        approval_path,
        json=approval_body,
        headers=approval_headers,
    )
    repeated_approval = api_client.post(
        approval_path,
        json=approval_body,
        headers=approval_headers,
    )
    assert approved.status_code == repeated_approval.status_code == 202
    assert repeated_approval.json()["id"] == approved.json()["id"]
    assert repeated_approval.json()["approval_reason"] == approved.json()["approval_reason"]
    assert repeated_approval.json()["approved_at"].rstrip("Z") == approved.json()[
        "approved_at"
    ].rstrip("Z")
    assert approved.json()["status"] == "APPROVED"
    approval_conflict = api_client.post(
        approval_path,
        json={**approval_body, "reason": "a different review reason"},
        headers=approval_headers,
    )
    assert approval_conflict.status_code == 409
    assert approval_conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

    simulation_publish = api_client.post(
        f"/api/v1/products/{simulation_l2['id']}:publish",
        json={"reason": "must remain simulation only"},
        headers=admin | {"Idempotency-Key": "publish-simulation-0001"},
    )
    assert simulation_publish.status_code == 409
    assert simulation_publish.json()["code"] == "SIMULATION_PUBLICATION_DISABLED"

    missing_reason = api_client.post(
        f"/api/v1/products/{l3['id']}:publish",
        json={"reason": None},
        headers=admin | {"Idempotency-Key": "publish-warning-0001"},
    )
    assert missing_reason.status_code == 409
    assert missing_reason.json()["code"] == "PRODUCT_WARNING_REASON_REQUIRED"

    publication_body = {"reason": "warning reviewed for formal publication"}
    publication_headers = admin | {"Idempotency-Key": "publish-product-0001"}
    published = api_client.post(
        f"/api/v1/products/{l3['id']}:publish",
        json=publication_body,
        headers=publication_headers,
    )
    repeated_publication = api_client.post(
        f"/api/v1/products/{l3['id']}:publish",
        json=publication_body,
        headers=publication_headers,
    )
    assert published.status_code == repeated_publication.status_code == 202
    assert published.json() == repeated_publication.json()
    assert published.json()["publication_status"] == "PUBLISHED"
    publication_conflict = api_client.post(
        f"/api/v1/products/{l3['id']}:publish",
        json={"reason": "a different publication reason"},
        headers=publication_headers,
    )
    assert publication_conflict.status_code == 409
    assert publication_conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

    withdrawn = api_client.post(
        f"/api/v1/products/{l3['id']}:withdraw",
        json={"reason": "withdrawn during release rehearsal"},
        headers=admin | {"Idempotency-Key": "withdraw-product-0001"},
    )
    assert withdrawn.status_code == 202
    assert withdrawn.json()["publication_status"] == "WITHDRAWN"


def test_sequence_can_pause_resume_and_preserve_committed_progress(
    api_client: TestClient, observer_headers: dict[str, str]
) -> None:
    payload = {"target_name": "PAUSE-RESUME", "mode": "POL_Q", "exposure_time": 500.0}
    created = api_client.post(
        "/api/v1/sequences",
        json=payload,
        headers=observer_headers | {"Idempotency-Key": "pause-sequence-0001"},
    )
    sequence_id = created.json()["resource_id"]
    api_client.post(
        f"/api/v1/sequences/{sequence_id}:start",
        headers=observer_headers | {"Idempotency-Key": "pause-start-0001"},
    )
    wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "RUNNING",
    )
    paused_request = api_client.post(
        f"/api/v1/sequences/{sequence_id}:pause",
        headers=observer_headers | {"Idempotency-Key": "pause-action-0001"},
    )
    assert paused_request.status_code == 202
    paused = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "PAUSED",
    )
    assert 1 <= paused["completed_exposures"] < 4
    resumed = api_client.post(
        f"/api/v1/sequences/{sequence_id}:resume",
        headers=observer_headers | {"Idempotency-Key": "pause-resume-0001"},
    )
    assert resumed.status_code == 202
    completed = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "SUCCEEDED",
    )
    assert completed["completed_exposures"] == 4
    exposures = api_client.get(
        f"/api/v1/sequences/{sequence_id}/exposures", headers=observer_headers
    ).json()
    assert len(exposures) == 4
    assert all(exposure["status"] == "COMMITTED" for exposure in exposures)


def test_sequence_abort_does_not_cross_the_l0_commit_boundary(
    api_client: TestClient, observer_headers: dict[str, str]
) -> None:
    payload = {"target_name": "ABORT", "mode": "NONPOL", "exposure_time": 500.0}
    created = api_client.post(
        "/api/v1/sequences",
        json=payload,
        headers=observer_headers | {"Idempotency-Key": "abort-sequence-0001"},
    )
    sequence_id = created.json()["resource_id"]
    api_client.post(
        f"/api/v1/sequences/{sequence_id}:start",
        headers=observer_headers | {"Idempotency-Key": "abort-start-0001"},
    )
    wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "RUNNING",
    )
    aborted_request = api_client.post(
        f"/api/v1/sequences/{sequence_id}:abort",
        headers=observer_headers | {"Idempotency-Key": "abort-action-0001"},
    )
    assert aborted_request.status_code == 202
    aborted = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "ABORTED",
    )
    assert aborted["completed_exposures"] == 0
    products = api_client.get(
        f"/api/v1/products?sequence_id={sequence_id}", headers=observer_headers
    ).json()
    assert not any(product["level"] == "L0" for product in products)


def test_disk_full_never_reports_l0_and_sequence_can_recover(
    api_client: TestClient, observer_headers: dict[str, str]
) -> None:
    engineer_headers = {
        "X-SPRITE-User": "test-engineer",
        "X-SPRITE-Role": "instrument_engineer",
    }
    fault_headers = engineer_headers | {"Idempotency-Key": "disk-full-on-0001"}
    injected = api_client.post("/sim/v1/faults/DISK_FULL?active=true", headers=fault_headers)
    assert injected.status_code == 202, injected.text
    repeated = api_client.post("/sim/v1/faults/DISK_FULL?active=true", headers=fault_headers)
    assert repeated.json() == injected.json()

    payload = {"target_name": "RECOVERY", "mode": "NONPOL", "exposure_time": 0.1}
    created = api_client.post(
        "/api/v1/sequences",
        json=payload,
        headers=observer_headers | {"Idempotency-Key": "recovery-sequence-0001"},
    )
    sequence_id = created.json()["resource_id"]
    api_client.post(
        f"/api/v1/sequences/{sequence_id}:start",
        headers=observer_headers | {"Idempotency-Key": "recovery-start-0001"},
    )
    failed = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "FAILED",
    )
    assert failed["completed_exposures"] == 0
    products = api_client.get(
        f"/api/v1/products?sequence_id={sequence_id}", headers=observer_headers
    ).json()
    assert not any(item["level"] == "L0" for item in products)
    exposures = api_client.get(
        f"/api/v1/sequences/{sequence_id}/exposures", headers=observer_headers
    ).json()
    assert len(exposures) == 1
    assert exposures[0]["status"] == "FAILED"

    cleared = api_client.post(
        "/sim/v1/faults/DISK_FULL?active=false",
        headers=engineer_headers | {"Idempotency-Key": "disk-full-off-0001"},
    )
    assert cleared.status_code == 202
    recovered = api_client.post(
        "/api/v1/instrument:recover",
        headers=engineer_headers | {"Idempotency-Key": "instrument-recover-0001"},
    )
    assert recovered.status_code == 202, recovered.text
    resumed = api_client.post(
        f"/api/v1/sequences/{sequence_id}:resume",
        headers=observer_headers | {"Idempotency-Key": "recovery-resume-0001"},
    )
    assert resumed.status_code == 202, resumed.text
    succeeded = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] in {"SUCCEEDED", "FAILED"} and value["attempt"] == 1,
    )
    assert succeeded["status"] == "SUCCEEDED", succeeded
    assert succeeded["completed_exposures"] == 1
    exposures = api_client.get(
        f"/api/v1/sequences/{sequence_id}/exposures", headers=observer_headers
    ).json()
    assert len(exposures) == 1
    assert exposures[0]["status"] == "COMMITTED"


@pytest.mark.parametrize(
    ("fault_type", "expected_code"),
    [
        ("STALE_STATE", "DEVICE_STATE_STALE"),
        ("LIMIT", "HARD_LIMIT_ACTIVE"),
        ("POSITION_TIMEOUT", "POSITION_NOT_REACHED"),
        ("GUIDER_LOST", "GUIDER_LOCK_LOST"),
        ("CCD_READOUT", "CCD_READOUT_FAILED"),
        ("INTERLOCK_OPEN", "INTERLOCK_UNSAFE"),
    ],
)
def test_control_faults_fail_safe_without_false_l0(
    api_client: TestClient,
    observer_headers: dict[str, str],
    fault_type: str,
    expected_code: str,
) -> None:
    engineer_headers = {
        "X-SPRITE-User": "test-engineer",
        "X-SPRITE-Role": "instrument_engineer",
        "Idempotency-Key": f"inject-{fault_type.lower()}-0001",
    }
    injected = api_client.post(f"/sim/v1/faults/{fault_type}?active=true", headers=engineer_headers)
    assert injected.status_code == 202
    created = api_client.post(
        "/api/v1/sequences",
        json={"target_name": fault_type, "mode": "NONPOL", "exposure_time": 0.1},
        headers=observer_headers | {"Idempotency-Key": f"sequence-{fault_type}-0001"},
    )
    sequence_id = created.json()["resource_id"]
    api_client.post(
        f"/api/v1/sequences/{sequence_id}:start",
        headers=observer_headers | {"Idempotency-Key": f"start-{fault_type}-0001"},
    )
    failed = wait_for(
        api_client,
        f"/api/v1/sequences/{sequence_id}",
        observer_headers,
        lambda value: value["status"] == "FAILED",
    )
    assert failed["last_error_code"] == expected_code
    products = api_client.get(
        f"/api/v1/products?sequence_id={sequence_id}", headers=observer_headers
    ).json()
    assert not any(item["level"] == "L0" for item in products)
    alarms = api_client.get("/api/v1/alarms", headers=observer_headers).json()
    assert alarms[0]["reason_code"] == expected_code
