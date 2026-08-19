"""Novedades: per-user "last dismissed CHANGELOG.md version" (see
app/services/patch_notes.py) so the "Novedades" modal auto-opens once per
user per panel update, instead of every page load.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("dismissed_patch_notes_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "dismissed_patch_notes_version")
