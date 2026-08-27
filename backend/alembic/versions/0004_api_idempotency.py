"""persist resource mutation idempotency

Revision ID: 0004_api_idempotency
Revises: 0003_espadons_import
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_api_idempotency"
down_revision: str | None = "0003_espadons_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    renamed_indexes = (
        (
            "calibration_runs",
            "ix_calibration_runs_batch",
            "ix_calibration_runs_import_batch_id",
            ["import_batch_id"],
        ),
        (
            "calibration_sets",
            "ix_calibration_sets_batch",
            "ix_calibration_sets_import_batch_id",
            ["import_batch_id"],
        ),
        (
            "calibration_sets",
            "ix_calibration_sets_night",
            "ix_calibration_sets_observing_night",
            ["observing_night"],
        ),
        (
            "calibrations",
            "ix_calibrations_set",
            "ix_calibrations_calibration_set_id",
            ["calibration_set_id"],
        ),
        (
            "import_batches",
            "ix_import_batches_manifest",
            "ix_import_batches_manifest_sha256",
            ["manifest_sha256"],
        ),
        (
            "import_inspections",
            "ix_import_inspections_manifest",
            "ix_import_inspections_manifest_sha256",
            ["manifest_sha256"],
        ),
        (
            "imported_artifacts",
            "ix_imported_artifacts_batch",
            "ix_imported_artifacts_import_batch_id",
            ["import_batch_id"],
        ),
        (
            "imported_artifacts",
            "ix_imported_artifacts_role",
            "ix_imported_artifacts_artifact_role",
            ["artifact_role"],
        ),
        (
            "imported_artifacts",
            "ix_imported_artifacts_sha",
            "ix_imported_artifacts_sha256",
            ["sha256"],
        ),
    )
    for table, old_name, new_name, columns in renamed_indexes:
        op.drop_index(old_name, table_name=table)
        op.create_index(new_name, table, columns)

    op.create_table(
        "api_idempotency_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("principal_hash", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope",
            "principal_hash",
            "key_hash",
            name="uq_api_idempotency_scope_principal_key",
        ),
    )
    op.create_index(
        "ix_api_idempotency_records_scope",
        "api_idempotency_records",
        ["scope"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_idempotency_records_scope",
        table_name="api_idempotency_records",
    )
    op.drop_table("api_idempotency_records")
    renamed_indexes = (
        (
            "calibration_runs",
            "ix_calibration_runs_import_batch_id",
            "ix_calibration_runs_batch",
            ["import_batch_id"],
        ),
        (
            "calibration_sets",
            "ix_calibration_sets_import_batch_id",
            "ix_calibration_sets_batch",
            ["import_batch_id"],
        ),
        (
            "calibration_sets",
            "ix_calibration_sets_observing_night",
            "ix_calibration_sets_night",
            ["observing_night"],
        ),
        (
            "calibrations",
            "ix_calibrations_calibration_set_id",
            "ix_calibrations_set",
            ["calibration_set_id"],
        ),
        (
            "import_batches",
            "ix_import_batches_manifest_sha256",
            "ix_import_batches_manifest",
            ["manifest_sha256"],
        ),
        (
            "import_inspections",
            "ix_import_inspections_manifest_sha256",
            "ix_import_inspections_manifest",
            ["manifest_sha256"],
        ),
        (
            "imported_artifacts",
            "ix_imported_artifacts_import_batch_id",
            "ix_imported_artifacts_batch",
            ["import_batch_id"],
        ),
        (
            "imported_artifacts",
            "ix_imported_artifacts_artifact_role",
            "ix_imported_artifacts_role",
            ["artifact_role"],
        ),
        (
            "imported_artifacts",
            "ix_imported_artifacts_sha256",
            "ix_imported_artifacts_sha",
            ["sha256"],
        ),
    )
    for table, new_name, old_name, columns in renamed_indexes:
        op.drop_index(new_name, table_name=table)
        op.create_index(old_name, table, columns)
