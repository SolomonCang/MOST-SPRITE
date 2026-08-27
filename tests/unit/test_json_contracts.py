from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


def load(relative_path: str) -> dict:
    return json.loads((SCHEMA_ROOT / relative_path).read_text(encoding="utf-8"))


def assert_valid(schema: dict, instance: dict) -> None:
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def test_public_api_envelopes_match_frozen_json_schemas() -> None:
    command_id = str(uuid4())
    assert_valid(
        load("api/accepted-v1.json"),
        {"command_id": command_id, "resource_id": str(uuid4()), "status": "ACCEPTED"},
    )
    assert_valid(
        load("api/error-v1.json"),
        {
            "code": "DEVICE_STATE_STALE",
            "message": "state is stale",
            "details": {"age_seconds": 7.0},
            "correlation_id": str(uuid4()),
            "retryable": True,
        },
    )


def test_versioned_event_envelope_matches_public_contract() -> None:
    assert_valid(
        load("events/event-envelope-v1.json"),
        {
            "cursor": 42,
            "event_id": str(uuid4()),
            "event_type": "raw_file.committed.v1",
            "schema_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "correlation_id": str(uuid4()),
            "causation_id": None,
            "sequence_id": str(uuid4()),
            "group_id": None,
            "exposure_id": str(uuid4()),
            "config_snapshot_id": str(uuid4()),
            "payload": {"sha256": "0" * 64},
        },
    )
