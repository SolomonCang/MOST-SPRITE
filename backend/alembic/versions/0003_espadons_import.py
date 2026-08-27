"""add ESPaDOnS import and calibration authority

Revision ID: 0003_espadons_import
Revises: 0002_processing_claim
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_espadons_import"
down_revision: str | None = "0002_processing_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_inspections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("root_id", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("instrument", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("inventory_json", sa.JSON(), nullable=False),
        sa.Column("groups_json", sa.JSON(), nullable=False),
        sa.Column("calibration_summary_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_import_inspections_manifest", "import_inspections", ["manifest_sha256"])
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("inspection_id", sa.String(36), sa.ForeignKey("import_inspections.id"), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sequence_ids_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_import_batches_manifest", "import_batches", ["manifest_sha256"])
    op.create_table(
        "calibration_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_batch_id", sa.String(36), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("parameter_version", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calibration_runs_batch", "calibration_runs", ["import_batch_id"])
    op.create_table(
        "calibration_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("calibration_run_id", sa.String(36), sa.ForeignKey("calibration_runs.id"), nullable=False, unique=True),
        sa.Column("import_batch_id", sa.String(36), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("instrument", sa.String(32), nullable=False),
        sa.Column("detector", sa.String(64), nullable=False),
        sa.Column("observing_night", sa.String(16), nullable=False),
        sa.Column("readout_mode", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("calibration_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("qc_flag", sa.String(32), nullable=False),
        sa.Column("qc_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calibration_sets_batch", "calibration_sets", ["import_batch_id"])
    op.create_index("ix_calibration_sets_instrument", "calibration_sets", ["instrument"])
    op.create_index("ix_calibration_sets_detector", "calibration_sets", ["detector"])
    op.create_index("ix_calibration_sets_night", "calibration_sets", ["observing_night"])
    op.create_table(
        "imported_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_batch_id", sa.String(36), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("managed_uri", sa.Text(), nullable=False, unique=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("artifact_role", sa.String(64), nullable=False),
        sa.Column("instrument", sa.String(32), nullable=False),
        sa.Column("detector", sa.String(64), nullable=False),
        sa.Column("header_json", sa.JSON(), nullable=False),
        sa.Column("sequence_id", sa.String(36), sa.ForeignKey("sequences.id"), nullable=True),
        sa.Column("exposure_id", sa.String(36), sa.ForeignKey("exposures.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("import_batch_id", "relative_path", name="uq_import_artifact_path"),
    )
    op.create_index("ix_imported_artifacts_batch", "imported_artifacts", ["import_batch_id"])
    op.create_index("ix_imported_artifacts_sha", "imported_artifacts", ["sha256"])
    op.create_index("ix_imported_artifacts_role", "imported_artifacts", ["artifact_role"])

    with op.batch_alter_table("raw_files") as batch_op:
        batch_op.add_column(sa.Column("instrument", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("detector_profile", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("source_format", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("imported_artifact_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_raw_import_artifact", "imported_artifacts", ["imported_artifact_id"], ["id"]
        )
    with op.batch_alter_table("processing_runs") as batch_op:
        batch_op.add_column(sa.Column("calibration_set_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "parameter_version",
                sa.String(64),
                nullable=False,
                server_default="simulation-v1",
            )
        )
        batch_op.add_column(
            sa.Column("parameters_json", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.create_foreign_key(
            "fk_processing_calset", "calibration_sets", ["calibration_set_id"], ["id"]
        )
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("instrument", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("detector_profile", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("import_batch_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("calibration_set_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "publication_status", sa.String(32), nullable=False, server_default="DRAFT"
            )
        )
        batch_op.add_column(sa.Column("published_by", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_product_import", "import_batches", ["import_batch_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_product_calset", "calibration_sets", ["calibration_set_id"], ["id"]
        )
    with op.batch_alter_table("calibrations") as batch_op:
        batch_op.add_column(sa.Column("calibration_set_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_calibration_set", "calibration_sets", ["calibration_set_id"], ["id"]
        )
    op.create_index("ix_calibrations_set", "calibrations", ["calibration_set_id"])


def downgrade() -> None:
    raise RuntimeError("0003 contains immutable import authority; downgrade is intentionally unsupported")
