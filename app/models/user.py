from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db

ROLES = ("owner", "admin", "member")
THEME_MODES = ("light", "dark", "system")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Enum(*ROLES, name="user_role"), nullable=False, default="member")
    quota_bytes: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    storage_used_bytes: Mapped[int] = mapped_column(db.BigInteger, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    theme_mode: Mapped[str] = mapped_column(Enum(*THEME_MODES, name="user_theme_mode"), nullable=False, default="system")
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # List of bcrypt-hashed one-time recovery codes (Fase 3) - consumed
    # (removed from the list) on use, same UX as GitHub/Google 2FA backup
    # codes. Never stores them in plaintext.
    totp_recovery_codes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    nodes: Mapped[list["Node"]] = relationship(back_populates="owner", foreign_keys="Node.owner_id")
    app_passwords: Mapped[list["AppPassword"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def get_id(self) -> str:  # Flask-Login expects a string id
        return str(self.id)

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")

    @property
    def storage_available_bytes(self) -> int:
        if self.quota_bytes == 0:
            # 0 is the sentinel for "no per-user cap" (admin/users.py
            # update_quota) - bounded only by the instance's own total
            # capacity instead of a fixed personal quota.
            from .instance_settings import InstanceSettings

            total = InstanceSettings.get_singleton().total_quota_bytes
            return max(total - self.storage_used_bytes, 0)
        return max(self.quota_bytes - self.storage_used_bytes, 0)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.username} ({self.role})>"
