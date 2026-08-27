from __future__ import annotations

import shutil
from uuid import UUID

from most_sprite.config import get_settings
from most_sprite.configuration import qc_configuration
from most_sprite.db.models import ConfigSnapshot
from most_sprite.domain.enums import ConfigurationStatus
from most_sprite.domain.schemas import SequenceRequest, SequenceValidation, ValidationIssue


def validate_sequence_request(
    request: SequenceRequest, snapshot: ConfigSnapshot
) -> SequenceValidation:
    issues: list[ValidationIssue] = []
    if snapshot.status != ConfigurationStatus.APPROVED:
        issues.append(
            ValidationIssue(
                code="UNVERIFIED_CONFIGURATION",
                message="instrument mappings remain unverified; outputs are simulation-only",
                blocking=False,
            )
        )
    free_bytes = shutil.disk_usage(get_settings().data_root).free
    if free_bytes < int(qc_configuration()["minimum_free_bytes"]):
        issues.append(
            ValidationIssue(
                code="STORAGE_HARD_LIMIT",
                message="less than 1 GiB is available for immutable raw data",
                blocking=True,
            )
        )
    per_repeat = 4 if request.mode.is_polarimetric else 1
    exposures = per_repeat * request.repeats
    return SequenceValidation(
        valid=not any(issue.blocking for issue in issues),
        estimated_exposures=exposures,
        estimated_duration=exposures * request.exposure_time,
        config_snapshot_id=UUID(snapshot.id),
        issues=issues,
    )
