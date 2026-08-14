from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for

from . import bp
from ...blueprints.auth.decorators import owner_required
from ...extensions import db
from ...models.instance_settings import InstanceSettings


@bp.route("/storage")
@owner_required
def edit_storage():
    settings = InstanceSettings.get_singleton()
    return render_template("admin/storage.html", settings=settings)


@bp.route("/storage", methods=["POST"])
@owner_required
def update_storage():
    settings = InstanceSettings.get_singleton()

    # total_quota_bytes is intentionally NOT accepted here: it's
    # provisioned externally by the hosting Dashboard via
    # INSTANCE_STORAGE_GB (.env/compose.yml) and resynced on every boot
    # (app/cli.py::_seed_instance_settings) - never admin/backend editable.
    default_user_quota_gb = request.form.get("default_user_quota_gb", type=int)
    max_upload_mb = request.form.get("max_upload_mb", type=int)
    trash_retention_days = request.form.get("trash_retention_days", type=int)
    version_retention_count = request.form.get("version_retention_count", type=int)
    allowed_extensions = request.form.get("allowed_extensions", "").strip()

    if default_user_quota_gb and default_user_quota_gb > 0:
        settings.default_user_quota_bytes = default_user_quota_gb * 1024**3
    if max_upload_mb and max_upload_mb > 0:
        settings.max_upload_mb = max_upload_mb
    if trash_retention_days and trash_retention_days > 0:
        settings.trash_retention_days = trash_retention_days
    if version_retention_count and version_retention_count > 0:
        settings.version_retention_count = version_retention_count
    settings.allowed_extensions = allowed_extensions or None
    settings.enforce_2fa_for_admins = request.form.get("enforce_2fa_for_admins") == "on"

    db.session.commit()
    flash("Configuracion de almacenamiento actualizada", "success")
    return redirect(url_for("admin.edit_storage"))
