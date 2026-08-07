from __future__ import annotations

from functools import wraps

from flask import jsonify, request
from flask_login import current_user, login_required

__all__ = ["login_required", "admin_required", "owner_required"]


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Se requieren permisos de administrador"}), 403
            return jsonify({"error": "Se requieren permisos de administrador"}), 403
        return view(*args, **kwargs)

    return wrapped


def owner_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_owner:
            return jsonify({"error": "Solo el propietario de la instancia puede hacer esto"}), 403
        return view(*args, **kwargs)

    return wrapped
