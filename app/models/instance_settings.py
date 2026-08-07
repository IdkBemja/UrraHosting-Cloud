from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InstanceSettings(db.Model):
    """Singleton row (one per instance) for storage/upload policy,
    seeded at boot from `INSTANCE_STORAGE_GB`/`DEFAULT_USER_QUOTA_GB`/etc
    (see config/platform_config.py) but editable afterwards from the
    Admin Panel's "Almacenamiento" tab without needing a redeploy.
    """

    __tablename__ = "instance_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    total_quota_bytes: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    default_user_quota_bytes: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    max_upload_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_extensions: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    trash_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    version_retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # Fase 3: when true, admin/owner accounts are forced into 2FA setup
    # before they can use anything else - enforced in
    # app/blueprints/auth/decorators.py, not just hidden in the UI.
    enforce_2fa_for_admins: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    @classmethod
    def get_singleton(cls) -> "InstanceSettings":
        instance = db.session.query(cls).first()
        if instance is None:
            raise RuntimeError("InstanceSettings no inicializado; ver app/cli.py::migrate")
        return instance
