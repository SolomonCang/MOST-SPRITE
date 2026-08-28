"""add preconfigured local user accounts

Revision ID: 0005_local_user_accounts
Revises: 0004_api_idempotency
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0005_local_user_accounts"
down_revision: str | None = "0004_api_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    created_at = datetime.now(UTC)
    table = op.create_table(
        "user_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_preconfigured", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_accounts_username", "user_accounts", ["username"], unique=True)
    op.create_index("ix_user_accounts_role", "user_accounts", ["role"])
    op.bulk_insert(
        table,
        [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "username": "administrator",
                "display_name": "Local Administrator",
                "role": "administrator",
                "is_active": True,
                "is_preconfigured": True,
                "created_at": created_at,
                "updated_at": created_at,
            },
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "username": "observer",
                "display_name": "Local Observer",
                "role": "observer",
                "is_active": True,
                "is_preconfigured": True,
                "created_at": created_at,
                "updated_at": created_at,
            },
            {
                "id": "00000000-0000-4000-8000-000000000003",
                "username": "instrument-engineer",
                "display_name": "Local Instrument Engineer",
                "role": "instrument_engineer",
                "is_active": True,
                "is_preconfigured": True,
                "created_at": created_at,
                "updated_at": created_at,
            },
            {
                "id": "00000000-0000-4000-8000-000000000004",
                "username": "data-reducer",
                "display_name": "Local Data Reducer",
                "role": "data_reducer",
                "is_active": True,
                "is_preconfigured": True,
                "created_at": created_at,
                "updated_at": created_at,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_user_accounts_role", table_name="user_accounts")
    op.drop_index("ix_user_accounts_username", table_name="user_accounts")
    op.drop_table("user_accounts")
