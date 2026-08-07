"""add generated tsvector column for full-text search on node names

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08

"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # STORED generated column (Postgres 12+): recomputed by Postgres
    # itself on every INSERT/UPDATE of `name`, never written from the
    # app - see app/models/node.py::Node.search_vector, mapped read-only.
    op.execute(
        "ALTER TABLE nodes ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, ''))) STORED"
    )
    op.execute("CREATE INDEX ix_nodes_search_vector ON nodes USING GIN (search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_search_vector")
    op.execute("ALTER TABLE nodes DROP COLUMN IF EXISTS search_vector")
