"""data fix: owner accounts seeded with the instance's total quota

`app/cli.py::_seed_owner` used to set the initial owner's `quota_bytes`
to `instance_settings.total_quota_bytes` (the whole instance's raw
capacity, e.g. INSTANCE_STORAGE_GB) instead of
`instance_settings.default_user_quota_bytes` (the actual per-user/plan
quota every other account gets). This corrects any owner row still
carrying that exact bug signature so WebDAV's quota-available-bytes
(RFC 4331, what Windows Explorer's drive gauge reads) reflects the real
assigned quota instead of the instance's total disk allocation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14

"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET quota_bytes = instance_settings.default_user_quota_bytes
        FROM instance_settings
        WHERE users.role = 'owner'
          AND users.quota_bytes = instance_settings.total_quota_bytes
          AND instance_settings.default_user_quota_bytes != instance_settings.total_quota_bytes
        """
    )


def downgrade() -> None:
    # The prior value was a bug (instance-wide capacity assigned to one
    # account); there's nothing correct to restore it to.
    pass
