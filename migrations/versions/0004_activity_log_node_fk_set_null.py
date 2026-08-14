"""activity_log.node_id FK: ON DELETE SET NULL

Purging a node (trash purge / WebDAV DELETE, see services/nodes.py::
delete_node_tree) hard-deletes the `nodes` row while historical
activity_log entries still point at it. The FK had no ON DELETE clause,
so Postgres raised ForeignKeyViolation and the request 500'd instead of
completing. The audit trail should survive the node being gone, not
block its deletion - same reasoning as user_id already being nullable.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14

"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("activity_log_node_id_fkey", "activity_log", type_="foreignkey")
    op.create_foreign_key(
        "activity_log_node_id_fkey",
        "activity_log",
        "nodes",
        ["node_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("activity_log_node_id_fkey", "activity_log", type_="foreignkey")
    op.create_foreign_key(
        "activity_log_node_id_fkey",
        "activity_log",
        "nodes",
        ["node_id"],
        ["id"],
    )
