"""2FA recovery codes + instance-wide enforcement policy (Fase 3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_recovery_codes_json", sa.JSON(), nullable=True))
    op.add_column(
        "instance_settings",
        sa.Column("enforce_2fa_for_admins", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("nodes", sa.Column("is_quarantined", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("nodes", "is_quarantined")
    op.drop_column("instance_settings", "enforce_2fa_for_admins")
    op.drop_column("users", "totp_recovery_codes_json")
