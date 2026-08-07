from __future__ import annotations

import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ...extensions import bcrypt, db, limiter
from ...models.user import User
from ...services import activity, twofactor

bp = Blueprint("auth", __name__)

_SESSION_PENDING_LOGIN_USER = "pending_2fa_user_id"


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("drive.my_drive"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter(
            (User.email.ilike(identifier)) | (User.username.ilike(identifier))
        ).first()

        if user and user.active and bcrypt.check_password_hash(user.password_hash, password):
            if user.totp_enabled:
                # Password alone isn't enough - stash the identity in the
                # (signed, server-side-verified) session and require the
                # second factor before login_user() ever runs, so no
                # Flask-Login session cookie exists until both factors
                # check out.
                session[_SESSION_PENDING_LOGIN_USER] = str(user.id)
                session["pending_2fa_next"] = request.args.get("next") or ""
                return redirect(url_for("auth.login_2fa"))

            login_user(user, remember=True)
            activity.record("login", user_id=user.id)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("drive.my_drive"))

        if user:
            activity.record("login_failed", user_id=user.id)
        flash("Credenciales invalidas", "error")

    return render_template("auth/login.html")


@bp.route("/login/2fa", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login_2fa():
    pending_id = session.get(_SESSION_PENDING_LOGIN_USER)
    if not pending_id:
        return redirect(url_for("auth.login"))

    user = db.session.get(User, uuid.UUID(pending_id))
    if user is None or not user.active or not user.totp_enabled:
        session.pop(_SESSION_PENDING_LOGIN_USER, None)
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code", "")
        valid = twofactor.verify_code(user.totp_secret, code) or twofactor.consume_recovery_code(user, code)
        if valid:
            db.session.commit()  # persists recovery-code consumption, if that's what matched
            session.pop(_SESSION_PENDING_LOGIN_USER, None)
            next_url = session.pop("pending_2fa_next", "") or None
            login_user(user, remember=True)
            activity.record("login", user_id=user.id)
            return redirect(next_url or url_for("drive.my_drive"))

        activity.record("login_2fa_failed", user_id=user.id)
        flash("Codigo invalido", "error")

    return render_template("auth/login_2fa.html")


@bp.route("/logout", methods=["POST"])
def logout():
    if current_user.is_authenticated:
        activity.record("logout", user_id=current_user.id)
    logout_user()
    return redirect(url_for("auth.login"))
