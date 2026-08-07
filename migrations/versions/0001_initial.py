"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-07

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("owner", "admin", "member", name="user_role"), nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("theme_mode", sa.Enum("light", "dark", "system", name="user_theme_mode"), nullable=False, server_default="system"),
        sa.Column("totp_secret", sa.String(64), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=True),
        sa.Column("type", sa.Enum("file", "folder", name="node_type"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("is_trashed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_nodes_owner_parent", "nodes", ["owner_id", "parent_id"])
    op.create_index(
        "ix_nodes_parent_name_active",
        "nodes",
        ["parent_id", "name"],
        unique=True,
        postgresql_where=sa.text("is_trashed = false"),
    )

    op.create_table(
        "file_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_file_versions_node_id", "file_versions", ["node_id"])

    op.create_table(
        "shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.Enum("user", "public_link", name="share_target_type"), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("token", sa.String(64), nullable=True),
        sa.Column("permission", sa.Enum("viewer", "editor", name="share_permission"), nullable=False, server_default="viewer"),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_shares_node_id", "shares", ["node_id"])
    op.create_index("ix_shares_token", "shares", ["token"])

    op.create_table(
        "app_passwords",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("scope", sa.Enum("webdav", "api", name="app_password_scope"), nullable=False, server_default="webdav"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_passwords_user_id", "app_passwords", ["user_id"])

    op.create_table(
        "activity_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_activity_log_action", "activity_log", ["action"])
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])

    op.create_table(
        "brand_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("app_name", sa.String(120), nullable=False, server_default="UrraHosting Cloud"),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("favicon_url", sa.String(500), nullable=True),
        sa.Column("theme_preset", sa.String(40), nullable=False, server_default="urrahosting"),
        sa.Column("primary", sa.String(9), nullable=False, server_default="#e25822"),
        sa.Column("secondary", sa.String(9), nullable=False, server_default="#ff4500"),
        sa.Column("accent", sa.String(9), nullable=False, server_default="#ff4081"),
        sa.Column("dark", sa.String(9), nullable=False, server_default="#1a1a1a"),
        sa.Column("light", sa.String(9), nullable=False, server_default="#f8f9fa"),
        sa.Column("supports_dark_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("dark_mode_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dark_overrides", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "instance_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("total_quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("default_user_quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_upload_mb", sa.Integer(), nullable=False),
        sa.Column("allowed_extensions", sa.String(1000), nullable=True),
        sa.Column("trash_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("version_retention_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("instance_settings")
    op.drop_table("brand_settings")
    op.drop_table("activity_log")
    op.drop_table("app_passwords")
    op.drop_table("shares")
    op.drop_table("file_versions")
    op.drop_table("nodes")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role")
    op.execute("DROP TYPE IF EXISTS user_theme_mode")
    op.execute("DROP TYPE IF EXISTS node_type")
    op.execute("DROP TYPE IF EXISTS share_target_type")
    op.execute("DROP TYPE IF EXISTS share_permission")
    op.execute("DROP TYPE IF EXISTS app_password_scope")
