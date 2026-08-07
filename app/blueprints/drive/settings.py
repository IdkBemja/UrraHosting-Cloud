from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import bcrypt, db
from ...models.app_password import AppPassword
from ...services import activity
from ...services.theming import get_brand


@bp.route("/settings")
@login_required
def settings():
    brand = get_brand()
    app_passwords = (
        AppPassword.query.filter_by(user_id=current_user.id, revoked_at=None)
        .order_by(AppPassword.created_at.desc())
        .all()
    )
    webdav_url = request.url_root.rstrip("/") + "/dav/"
    return render_template(
        "drive/settings.html",
        brand=brand,
        app_passwords=app_passwords,
        webdav_url=webdav_url,
        new_password=None,
    )


@bp.route("/settings/theme", methods=["POST"])
@login_required
def update_theme():
    brand = get_brand()
    if not brand.supports_dark_mode:
        flash("El administrador de esta instancia desactivo la eleccion de tema", "error")
        return redirect(url_for("drive.settings"))

    mode = request.form.get("theme_mode", "system")
    if mode not in ("light", "dark", "system"):
        mode = "system"
    current_user.theme_mode = mode
    db.session.commit()
    return redirect(url_for("drive.settings"))


@bp.route("/settings/app-passwords", methods=["POST"])
@login_required
def create_app_password():
    label = request.form.get("label", "").strip() or "Dispositivo sin nombre"
    plaintext = secrets.token_urlsafe(18)  # shown once, never recoverable afterwards

    app_password = AppPassword(
        user_id=current_user.id,
        label=label,
        password_hash=bcrypt.generate_password_hash(plaintext).decode("utf-8"),
        scope="webdav",
    )
    db.session.add(app_password)
    db.session.commit()
    activity.record("app_password_created", user_id=current_user.id)

    brand = get_brand()
    app_passwords = (
        AppPassword.query.filter_by(user_id=current_user.id, revoked_at=None)
        .order_by(AppPassword.created_at.desc())
        .all()
    )
    webdav_url = request.url_root.rstrip("/") + "/dav/"
    return render_template(
        "drive/settings.html",
        brand=brand,
        app_passwords=app_passwords,
        webdav_url=webdav_url,
        new_password=plaintext,
        new_password_label=label,
    )


@bp.route("/settings/app-passwords/<uuid:app_password_id>/revoke", methods=["POST"])
@login_required
def revoke_app_password(app_password_id: uuid.UUID):
    app_password = AppPassword.query.filter_by(id=app_password_id, user_id=current_user.id).first()
    if app_password is not None and app_password.is_active:
        app_password.revoked_at = datetime.now(timezone.utc)
        db.session.commit()
        activity.record("app_password_revoked", user_id=current_user.id)
    return redirect(url_for("drive.settings"))
