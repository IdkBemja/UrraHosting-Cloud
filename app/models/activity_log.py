from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActivityLog(db.Model):
    """Relational audit trail (replaces WebPanel's flat NDJSON log) so the
    Admin Panel can filter/paginate by user, action or date directly with
    SQL instead of scanning a file.
    """

    __tablename__ = "activity_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # ON DELETE SET NULL: the audit trail must outlive the node it
    # references (purge/WebDAV DELETE hard-delete the row) - see
    # migrations/versions/0004_activity_log_node_fk_set_null.py.
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
