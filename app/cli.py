"""`python -m app.cli migrate` - run on every `app` container boot
(see compose.yml). Applies pending Alembic migrations, then seeds the
singleton settings rows and the initial owner account from
APP_USER/APP_PASSWORD (same bootstrap pattern as WebPanel, adapted to a
real users table instead of a single hardcoded admin).
"""

from __future__ import annotations

import sys

from alembic import command
from alembic.config import Config

from .extensions import bcrypt, db
from .main import create_app
from .models.brand_settings import BrandSettings
from .models.instance_settings import InstanceSettings
from .models.user import User
from .services.nodes import create_user_root


def _run_alembic_upgrade() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


def _seed_instance_settings(app) -> None:
    if db.session.query(InstanceSettings).first() is not None:
        return
    config = app.config["INSTANCE"]
    db.session.add(
        InstanceSettings(
            total_quota_bytes=config.instance_storage_gb * 1024**3,
            default_user_quota_bytes=config.default_user_quota_gb * 1024**3,
            max_upload_mb=config.max_upload_mb,
            trash_retention_days=config.trash_retention_days,
            version_retention_count=config.version_retention_count,
        )
    )
    db.session.commit()


def _seed_owner(app) -> None:
    if db.session.query(User).first() is not None:
        return
    config = app.config["INSTANCE"]
    settings = InstanceSettings.get_singleton()
    owner = User(
        email=config.app_user,
        username=config.app_user.split("@")[0][:64],
        password_hash=bcrypt.generate_password_hash(config.app_password).decode("utf-8"),
        role="owner",
        quota_bytes=settings.total_quota_bytes,
    )
    db.session.add(owner)
    db.session.flush()
    create_user_root(owner)
    db.session.commit()
    print(f"[cloud] Owner inicial creado: {owner.email}")


def migrate() -> None:
    _run_alembic_upgrade()
    # `from .main import create_app` above already ran create_app() once
    # (main.py builds its module-level `app` for gunicorn on import); this
    # second call is a cheap, idempotent re-init (config parsing + mkdir
    # -p), not a real double-boot, and keeps this module usable without
    # depending on main.py's import side effect.
    app = create_app()
    with app.app_context():
        BrandSettings.get_singleton()  # creates the row with defaults if missing
        _seed_instance_settings(app)
        _seed_owner(app)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "migrate":
        print("Uso: python -m app.cli migrate")
        sys.exit(1)
    migrate()
