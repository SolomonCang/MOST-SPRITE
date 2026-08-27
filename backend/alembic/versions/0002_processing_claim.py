"""add_processing_run_claim

Revision ID: 0002_processing_claim
Revises: 0001_initial
Create Date: 2026-08-26 17:36:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_processing_claim"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "processing_runs",
        sa.Column("claim_token", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "processing_runs",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("processing_runs", "claimed_at")
    op.drop_column("processing_runs", "claim_token")
