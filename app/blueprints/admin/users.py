from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from . import bp
from ...blueprints.auth.decorators import admin_required, owner_required
from ...extensions import bcrypt, db
from ...models.instance_settings import InstanceSettings
from ...models.user import User
from ...services import activity
from ...services.nodes import create_user_root

_MIN_PASSWORD_LENGTH = 10


@bp.route("/users")
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.asc()).all()
    return render_template("admin/users.html", users=users)


@bp.route("/users", methods=["POST"])
@admin_required
def create_user():
    email = request.form.get("email", "").strip().lower()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "member")
    quota_gb = request.form.get("quota_gb", type=int)

    if role not in ("admin", "member"):
        role = "member"  # only an existing owner can be promoted to owner, never via this form
    if len(password) < _MIN_PASSWORD_LENGTH:
        flash(f"La contraseña debe tener al menos {_MIN_PASSWORD_LENGTH} caracteres", "error")
        return redirect(url_for("admin.list_users"))
    if User.query.filter((User.email == email) | (User.username == username)).first():
        flash("Ya existe un usuario con ese email o nombre de usuario", "error")
        return redirect(url_for("admin.list_users"))

    settings = InstanceSettings.get_singleton()
    quota_bytes = (quota_gb * 1024**3) if quota_gb else settings.default_user_quota_bytes

    user = User(
        email=email,
        username=username,
        password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
        role=role,
        quota_bytes=quota_bytes,
    )
    db.session.add(user)
    db.session.flush()
    create_user_root(user)
    db.session.commit()
    activity.record("user_created", user_id=current_user.id)
    flash(f"Usuario '{username}' creado", "success")
    return redirect(url_for("admin.list_users"))


@bp.route("/users/<uuid:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_active(user_id):
    user = db.get_or_404(User, user_id)
    if user.is_owner:
        flash("No se puede suspender al propietario de la instancia", "error")
        return redirect(url_for("admin.list_users"))
    user.active = not user.active
    db.session.commit()
    activity.record("user_suspended" if not user.active else "user_reactivated", user_id=current_user.id, node_id=None)
    return redirect(url_for("admin.list_users"))


@bp.route("/users/<uuid:user_id>/quota", methods=["POST"])
@owner_required
def update_quota(user_id):
    # owner_required (not admin_required): unlike everything else on this
    # page, quota changes affect how much of the instance's own paid
    # capacity an account can consume - including setting it to
    # unlimited - so this is reserved for the owner, same reasoning as
    # /admin/storage. Deliberately has no is_owner exclusion: the owner
    # editing their own row (e.g. to go unlimited) is the main use case.
    user = db.get_or_404(User, user_id)
    raw = request.form.get("quota_gb", "").strip()

    if raw == "":
        # Blank: reset to the instance's current default user quota.
        user.quota_bytes = InstanceSettings.get_singleton().default_user_quota_bytes
        flash(f"Cuota de '{user.username}' restablecida al valor por defecto", "success")
    else:
        quota_gb = int(raw) if raw.lstrip("-").isdigit() else None
        if quota_gb is None or quota_gb < 0:
            flash("Cuota invalida", "error")
            return redirect(url_for("admin.list_users"))
        if quota_gb == 0:
            user.quota_bytes = 0  # sentinel: unlimited, capped only by the instance's total quota
            flash(f"Cuota de '{user.username}' establecida como ilimitada", "success")
        else:
            user.quota_bytes = quota_gb * 1024**3
            flash(f"Cuota de '{user.username}' actualizada a {quota_gb} GB", "success")

    db.session.commit()
    return redirect(url_for("admin.list_users"))
