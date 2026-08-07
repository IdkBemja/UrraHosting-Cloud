from __future__ import annotations

import mimetypes
import uuid

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...models.file_version import FileVersion
from ...models.instance_settings import InstanceSettings
from ...models.node import Node
from ...services import activity, jobs
from ...services.nodes import delete_node_tree, get_user_root, restore_node_tree, trash_node_tree
from ...services.quota import apply_usage_delta, check_user_quota
from ...services.storage.base import StorageError

INLINE_PREVIEW_MIME_PREFIXES = ("image/", "text/")
INLINE_PREVIEW_MIME_EXACT = {"application/pdf"}
INLINE_PREVIEW_MAX_BYTES = 20 * 1024 * 1024


def _breadcrumbs(node: Node) -> list[Node]:
    trail = []
    current = node
    while current is not None and current.parent_id is not None:
        current = Node.query.get(current.parent_id)
        if current is not None:
            trail.append(current)
    trail.reverse()
    return trail


def _get_owned_folder(node_id: uuid.UUID) -> Node:
    node = Node.query.filter_by(id=node_id, owner_id=current_user.id, is_trashed=False).first()
    if node is None or node.type != "folder":
        abort(404)
    return node


def _get_owned_file(node_id: uuid.UUID) -> Node:
    node = Node.query.filter_by(id=node_id, owner_id=current_user.id, is_trashed=False, type="file").first()
    if node is None:
        abort(404)
    return node


@bp.route("/")
@login_required
def my_drive():
    root = get_user_root(current_user)
    return redirect(url_for("drive.browse", node_id=root.id))


@bp.route("/folder/<uuid:node_id>")
@login_required
def browse(node_id):
    folder = _get_owned_folder(node_id)
    children = (
        Node.query.filter_by(parent_id=folder.id, is_trashed=False)
        .order_by(Node.type.desc(), Node.name.asc())
        .all()
    )
    return render_template(
        "drive/browse.html",
        folder=folder,
        children=children,
        breadcrumbs=_breadcrumbs(folder),
    )


@bp.route("/folder/<uuid:node_id>/mkdir", methods=["POST"])
@login_required
def mkdir(node_id):
    parent = _get_owned_folder(node_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("El nombre de la carpeta no puede estar vacio", "error")
        return redirect(url_for("drive.browse", node_id=parent.id))

    exists = Node.query.filter_by(parent_id=parent.id, name=name, is_trashed=False).first()
    if exists:
        flash(f"Ya existe '{name}' en esta carpeta", "error")
        return redirect(url_for("drive.browse", node_id=parent.id))

    folder = Node(owner_id=current_user.id, parent_id=parent.id, type="folder", name=name)
    db.session.add(folder)
    db.session.commit()
    activity.record("folder_created", user_id=current_user.id, node_id=folder.id)
    return redirect(url_for("drive.browse", node_id=parent.id))


def _snapshot_previous_version(node: Node) -> None:
    """Copies the current blob of an existing file node into version
    storage before it gets overwritten - called right before
    `storage.save()` replaces the live blob in place (plan.md Fase 2:
    versioning). A node with no prior content (never uploaded, e.g. just
    created via WebDAV LOCK) has nothing worth snapshotting.
    """
    if node.size_bytes == 0 and node.checksum_sha256 is None:
        return
    storage = current_app.config["STORAGE"]
    version_id = uuid.uuid4()
    with storage.open(node.id) as old_blob:
        storage.save_version(node.id, version_id, old_blob, max_bytes=node.size_bytes + 1)
    db.session.add(
        FileVersion(
            id=version_id,
            node_id=node.id,
            size_bytes=node.size_bytes,
            checksum_sha256=node.checksum_sha256,
            created_by=node.owner_id,
        )
    )


@bp.route("/folder/<uuid:node_id>/upload", methods=["POST"])
@login_required
def upload(node_id):
    parent = _get_owned_folder(node_id)
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        flash("Selecciona un archivo", "error")
        return redirect(url_for("drive.browse", node_id=parent.id))

    name = uploaded.filename.replace("\\", "/").split("/")[-1].strip()
    if not name or name in (".", ".."):
        flash("Nombre de archivo invalido", "error")
        return redirect(url_for("drive.browse", node_id=parent.id))

    max_bytes = InstanceSettings.get_singleton().max_upload_mb * 1024 * 1024
    existing = Node.query.filter_by(parent_id=parent.id, name=name, is_trashed=False).first()
    node = existing or Node(owner_id=current_user.id, parent_id=parent.id, type="file", name=name)
    is_new = existing is None
    if is_new:
        db.session.add(node)
    db.session.flush()

    try:
        check_user_quota(current_user, max_bytes)  # optimistic pre-check; storage.save enforces the hard byte cap
        if not is_new:
            _snapshot_previous_version(node)
        stat = current_app.config["STORAGE"].save(node.id, uploaded.stream, max_bytes)
    except StorageError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("drive.browse", node_id=parent.id))

    delta = stat.size_bytes - (0 if is_new else node.size_bytes)
    node.size_bytes = stat.size_bytes
    node.checksum_sha256 = stat.checksum_sha256
    node.mime_type = mimetypes.guess_type(name)[0]
    apply_usage_delta(current_user, delta)
    db.session.commit()
    activity.record("upload", user_id=current_user.id, node_id=node.id)
    jobs.enqueue_virus_scan(node.id)
    flash(f"'{name}' subido", "success")
    return redirect(url_for("drive.browse", node_id=parent.id))


@bp.route("/download/<uuid:node_id>")
@login_required
def download(node_id):
    node = _get_owned_file(node_id)
    if node.is_quarantined:
        abort(403, "Este archivo fue marcado como potencialmente malicioso por el escaneo antivirus")
    try:
        handle = current_app.config["STORAGE"].open(node.id)
    except StorageError:
        abort(404)
    activity.record("download", user_id=current_user.id, node_id=node.id)
    return send_file(
        handle,
        mimetype=node.mime_type or "application/octet-stream",
        as_attachment=True,
        download_name=node.name,
    )


def _is_previewable(mime_type: str | None) -> bool:
    if not mime_type:
        return False
    return mime_type in INLINE_PREVIEW_MIME_EXACT or mime_type.startswith(INLINE_PREVIEW_MIME_PREFIXES)


@bp.route("/preview/<uuid:node_id>")
@login_required
def preview(node_id):
    """Inline preview (Fase 2): images/PDF/text rendered in the browser
    instead of downloaded. Anything else - or anything over
    INLINE_PREVIEW_MAX_BYTES - falls back to a normal attachment
    download, since streaming a huge file inline just to render a
    "can't preview this" message is wasted bandwidth.
    """
    node = _get_owned_file(node_id)
    if node.is_quarantined:
        abort(403, "Este archivo fue marcado como potencialmente malicioso por el escaneo antivirus")
    if not _is_previewable(node.mime_type) or node.size_bytes > INLINE_PREVIEW_MAX_BYTES:
        return redirect(url_for("drive.download", node_id=node.id))
    try:
        handle = current_app.config["STORAGE"].open(node.id)
    except StorageError:
        abort(404)
    return send_file(handle, mimetype=node.mime_type, as_attachment=False, download_name=node.name)


@bp.route("/trash-node/<uuid:node_id>", methods=["POST"])
@login_required
def trash_node(node_id):
    node = Node.query.filter_by(id=node_id, owner_id=current_user.id, is_trashed=False).first()
    if node is None:
        abort(404)
    parent_id = node.parent_id
    trash_node_tree(node)
    db.session.commit()
    activity.record("trashed", user_id=current_user.id, node_id=node.id)
    return redirect(url_for("drive.browse", node_id=parent_id))


@bp.route("/trash")
@login_required
def trash():
    all_trashed = Node.query.filter_by(owner_id=current_user.id, is_trashed=True).all()
    trashed_ids = {n.id for n in all_trashed}
    # Only top-level trashed items (parent not itself trashed) - same
    # filtering as worker/tasks.py::purge_expired_trash, so a trashed
    # folder's cascaded descendants don't clutter the listing.
    top_level = [n for n in all_trashed if n.parent_id not in trashed_ids]
    top_level.sort(key=lambda n: n.trashed_at or n.updated_at, reverse=True)
    return render_template("drive/trash.html", items=top_level)


@bp.route("/trash/<uuid:node_id>/restore", methods=["POST"])
@login_required
def restore(node_id):
    node = Node.query.filter_by(id=node_id, owner_id=current_user.id, is_trashed=True).first()
    if node is None:
        abort(404)
    restore_node_tree(node)
    db.session.commit()
    activity.record("restored", user_id=current_user.id, node_id=node.id)
    return redirect(url_for("drive.trash"))


@bp.route("/trash/<uuid:node_id>/purge", methods=["POST"])
@login_required
def purge(node_id):
    node = Node.query.filter_by(id=node_id, owner_id=current_user.id, is_trashed=True).first()
    if node is None:
        abort(404)
    delete_node_tree(current_app.config["STORAGE"], node)
    db.session.commit()
    activity.record("purged", user_id=current_user.id)
    return redirect(url_for("drive.trash"))
