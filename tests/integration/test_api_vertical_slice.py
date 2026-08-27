from __future__ import annotations

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

    reducer_headers = {
        "X-SPRITE-User": "test-reducer",
        "X-SPRITE-Role": "data_reducer",
    }
    first_profile = api_client.post(
        "/api/v1/processing-runs",
        json={"sequence_id": sequence_id, "parameters": {"profile": "regression-A"}},
        headers=reducer_headers | {"Idempotency-Key": f"run-a-{sequence_id}"},
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
        repeated_profile.status_code,
        second_profile.status_code,
    } == {202}
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
