from __future__ import annotations

import pytest
from flask import Flask

from app.extensions import bcrypt, db
from app.models.user import User


@pytest.fixture
def app():
    """Minimal Flask app bound to an in-memory sqlite DB, with only the
    `users` table created - enough for services that only touch `User`
    (e.g. services/quota.py, services/twofactor.py) without needing the
    full Postgres-only schema (brand_settings.dark_overrides is JSONB,
    sqlite can't render it - see the models/__init__ import needing
    Postgres in practice).
    """
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    db.init_app(flask_app)
    bcrypt.init_app(flask_app)
    with flask_app.app_context():
        User.__table__.create(db.engine)
        yield flask_app
        db.session.remove()
