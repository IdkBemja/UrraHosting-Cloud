from __future__ import annotations

import uuid

from flask import abort, current_app, render_template, redirect, send_file, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...models.file_version import FileVersion
from ...models.instance_settings import InstanceSettings
from ...models.node import Node
from ...services import activity
from ...services.quota import apply_usage_delta, check_user_quota
from ...services.storage.base import StorageError
from .routes import _get_owned_file, _snapshot_previous_version


@bp.route("/versions/<uuid:node_id>")
@login_required
def list_versions(node_id):
    node = _get_owned_file(node_id)
    versions = FileVersion.query.filter_by(node_id=node.id).order_by(FileVersion.created_at.desc()).all()
    return render_template("drive/versions.html", node=node, versions=versions)


@bp.route("/versions/<uuid:node_id>/download/<uuid:version_id>")
@login_required
def download_version(node_id, version_id):
    node = _get_owned_file(node_id)
    version = FileVersion.query.filter_by(id=version_id, node_id=node.id).first()
    if version is None:
        abort(404)
    try:
        handle = current_app.config["STORAGE"].open_version(node.id, version.id)
    except StorageError:
        abort(404)
    return send_file(handle, mimetype=node.mime_type or "application/octet-stream", as_attachment=True, download_name=node.name)


@bp.route("/versions/<uuid:node_id>/restore/<uuid:version_id>", methods=["POST"])
@login_required
def restore_version(node_id, version_id):
    """Restoring an old version snapshots the CURRENT content as a new
    version first (so restoring is itself undoable), then copies the old
    version's blob back into the live blob slot.
    """
    node = _get_owned_file(node_id)
    version = FileVersion.query.filter_by(id=version_id, node_id=node.id).first()
    if version is None:
        abort(404)

    storage = current_app.config["STORAGE"]
    max_bytes = InstanceSettings.get_singleton().max_upload_mb * 1024 * 1024
    try:
        check_user_quota(current_user, max(version.size_bytes - node.size_bytes, 0))
        _snapshot_previous_version(node)
        with storage.open_version(node.id, version.id) as old_content:
            stat = storage.save(node.id, old_content, max_bytes)
    except StorageError as exc:
        db.session.rollback()
        abort(400, str(exc))

    delta = stat.size_bytes - node.size_bytes
    node.size_bytes = stat.size_bytes
    node.checksum_sha256 = stat.checksum_sha256
    apply_usage_delta(current_user, delta)
    db.session.commit()
    activity.record("version_restored", user_id=current_user.id, node_id=node.id)
    return redirect(url_for("drive.list_versions", node_id=node.id))
