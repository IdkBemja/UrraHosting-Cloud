from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db

# "UrraHosting Theme (por defecto)" - paleta heredada 1:1 de main.css del
# Dashboard (docker-host), ver plan.md seccion 7.1. Toda instancia nueva
# arranca con esto sin que el cliente tenga que configurar nada.
DEFAULT_APP_NAME = "UrraHosting Cloud"
DEFAULT_PRESET = "urrahosting"
DEFAULT_PRIMARY = "#e25822"
DEFAULT_SECONDARY = "#ff4500"
DEFAULT_ACCENT = "#ff4081"
DEFAULT_DARK = "#1a1a1a"
DEFAULT_LIGHT = "#f8f9fa"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BrandSettings(db.Model):
    """Singleton row (one per instance) driving `/theme.css` and the
    branding shown across Admin Panel + Drive App. `logo_url`/
    `favicon_url` are nullable on purpose: `services/theming.py` resolves
    a missing value to the bundled UrraHosting default asset so an
    instance is never shown without a logo/favicon (plan.md seccion 7.1).
    """

    __tablename__ = "brand_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_name: Mapped[str] = mapped_column(String(120), nullable=False, default=DEFAULT_APP_NAME)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    favicon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    theme_preset: Mapped[str] = mapped_column(String(40), nullable=False, default=DEFAULT_PRESET)
    primary: Mapped[str] = mapped_column(String(9), nullable=False, default=DEFAULT_PRIMARY)
    secondary: Mapped[str] = mapped_column(String(9), nullable=False, default=DEFAULT_SECONDARY)
    accent: Mapped[str] = mapped_column(String(9), nullable=False, default=DEFAULT_ACCENT)
    dark: Mapped[str] = mapped_column(String(9), nullable=False, default=DEFAULT_DARK)
    light: Mapped[str] = mapped_column(String(9), nullable=False, default=DEFAULT_LIGHT)
    supports_dark_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dark_mode_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional fine-grained overrides for the dark variant (surface/text/
    # border tokens); when absent, theming.py derives sensible dark
    # values from `dark`/`light`/`primary` automatically.
    dark_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    @classmethod
    def get_singleton(cls) -> "BrandSettings":
        instance = db.session.query(cls).first()
        if instance is None:
            instance = cls()
            db.session.add(instance)
            db.session.commit()
        return instance
