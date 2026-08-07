from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db

SCOPES = ("webdav", "api")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppPassword(db.Model):
    """Secondary credential for WebDAV/sync clients (Nextcloud pattern):
    never the user's main login password, so it can be scoped, listed,
    and revoked independently and doesn't carry 2FA semantics.
    """

    __tablename__ = "app_passwords"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(Enum(*SCOPES, name="app_password_scope"), nullable=False, default="webdav")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="app_passwords")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
