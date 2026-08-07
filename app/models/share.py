from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db

TARGET_TYPES = ("user", "public_link")
PERMISSIONS = ("viewer", "editor")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Share(db.Model):
    __tablename__ = "shares"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(Enum(*TARGET_TYPES, name="share_target_type"), nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    permission: Mapped[str] = mapped_column(Enum(*PERMISSIONS, name="share_permission"), nullable=False, default="viewer")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    node: Mapped["Node"] = relationship(back_populates="shares")
    target_user: Mapped["User | None"] = relationship(foreign_keys=[target_user_id])

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at < _utcnow())
