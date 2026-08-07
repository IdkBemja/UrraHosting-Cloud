from __future__ import annotations

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import bcrypt, db
from ...services import activity, twofactor
from ...services.theming import get_brand

_SESSION_PENDING_SECRET = "pending_totp_secret"


@bp.route("/settings/2fa/setup")
@login_required
def setup_2fa():
    if current_user.totp_enabled:
        flash("La verificacion en dos pasos ya esta activada", "success")
        return redirect(url_for("drive.settings"))

    secret = session.get(_SESSION_PENDING_SECRET)
    if not secret:
        secret = twofactor.generate_secret()
        session[_SESSION_PENDING_SECRET] = secret

    brand = get_brand()
    uri = twofactor.provisioning_uri(current_user, secret, brand.app_name)
    qr_data_uri = twofactor.qr_code_data_uri(uri)
    return render_template("drive/setup_2fa.html", secret=secret, qr_data_uri=qr_data_uri)


@bp.route("/settings/2fa/setup", methods=["POST"])
@login_required
def confirm_2fa():
    secret = session.get(_SESSION_PENDING_SECRET)
    code = request.form.get("code", "")
    if not secret or not twofactor.verify_code(secret, code):
        flash("Codigo invalido. Intenta nuevamente.", "error")
        return redirect(url_for("drive.setup_2fa"))

    plaintext_codes = twofactor.generate_recovery_codes()
    current_user.totp_secret = secret
    current_user.totp_enabled = True
    current_user.totp_recovery_codes_json = twofactor.hash_recovery_codes(plaintext_codes)
    db.session.commit()
    session.pop(_SESSION_PENDING_SECRET, None)
    activity.record("2fa_enabled", user_id=current_user.id)
    return render_template("drive/setup_2fa_done.html", recovery_codes=plaintext_codes)


@bp.route("/settings/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    password = request.form.get("password", "")
    if not bcrypt.check_password_hash(current_user.password_hash, password):
        flash("Contrasena incorrecta", "error")
        return redirect(url_for("drive.settings"))

    current_user.totp_secret = None
    current_user.totp_enabled = False
    current_user.totp_recovery_codes_json = None
    db.session.commit()
    activity.record("2fa_disabled", user_id=current_user.id)
    flash("Verificacion en dos pasos desactivada", "success")
    return redirect(url_for("drive.settings"))
