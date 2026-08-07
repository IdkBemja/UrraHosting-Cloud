"""Resumable/chunked upload (Fase 2, plan.md section 5.2): lets the
browser split a large file into fixed-size chunks and POST them one at a
time, so a dropped connection loses only the current chunk instead of
the whole upload. Deliberately simple compared to a full tus.io
implementation: chunks must arrive in order (enforced server-side via a
sidecar `.meta` file tracking the next expected index) - good enough for
a same-origin browser client that already knows how many chunks it sent,
without pulling in an external protocol/library.

`upload_id` is client-generated but only ever used after being validated
as a UUID (see `_safe_upload_id`), so it can never become a path-
traversal vector even though it's attacker-controlled input.
"""

from __future__ import annotations

import json
import uuid

from flask import abort, current_app, jsonify, request
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...models.instance_settings import InstanceSettings
from ...models.node import Node
from ...services import activity, jobs
from ...services.quota import apply_usage_delta, check_user_quota
from ...services.storage.base import StorageError
from .routes import _get_owned_folder, _snapshot_previous_version


def _safe_upload_id(raw: str) -> str:
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        abort(400, "upload_id invalido")


def _meta_path(upload_id: str):
    return current_app.config["TMP_UPLOADS_DIR"] / f"{upload_id}.meta.json"


def _data_path(upload_id: str):
    return current_app.config["TMP_UPLOADS_DIR"] / f"{upload_id}.part"


@bp.route("/upload-chunk/<upload_id>/status")
@login_required
def chunk_status(upload_id):
    upload_id = _safe_upload_id(upload_id)
    meta_path = _meta_path(upload_id)
    if not meta_path.exists():
        return jsonify({"next_chunk_index": 0})
    meta = json.loads(meta_path.read_text())
    if meta["user_id"] != str(current_user.id):
        abort(404)
    return jsonify({"next_chunk_index": meta["received_chunks"]})


@bp.route("/upload-chunk", methods=["POST"])
@login_required
def upload_chunk():
    upload_id = _safe_upload_id(request.form.get("upload_id", ""))
    chunk_index = request.form.get("chunk_index", type=int)
    total_chunks = request.form.get("total_chunks", type=int)
    parent_id = request.form.get("parent_id", "")
    filename = request.form.get("filename", "").strip()
    chunk = request.files.get("chunk")

    if chunk_index is None or total_chunks is None or not chunk or not filename:
        abort(400, "Parametros de chunk invalidos")

    try:
        parent_uuid = uuid.UUID(parent_id)
    except (ValueError, AttributeError, TypeError):
        abort(400, "parent_id invalido")
    parent = _get_owned_folder(parent_uuid)

    meta_path = _meta_path(upload_id)
    data_path = _data_path(upload_id)

    if chunk_index == 0:
        meta = {"user_id": str(current_user.id), "parent_id": str(parent.id), "filename": filename, "total_chunks": total_chunks, "received_chunks": 0}
        if data_path.exists():
            data_path.unlink()
    elif not meta_path.exists():
        abort(409, "No existe una subida en progreso con ese upload_id (reinicia desde el chunk 0)")
    else:
        meta = json.loads(meta_path.read_text())
        if meta["user_id"] != str(current_user.id):
            abort(404)
        if chunk_index != meta["received_chunks"]:
            # Client is out of sync (e.g. retried a chunk the server
            # already has) - tell it exactly where the server really is
            # instead of silently corrupting the file by writing out of
            # order.
            return jsonify({"error": "out_of_order", "next_chunk_index": meta["received_chunks"]}), 409

    with open(data_path, "ab") as handle:
        handle.write(chunk.read())

    meta["received_chunks"] = chunk_index + 1
    meta_path.write_text(json.dumps(meta))

    if meta["received_chunks"] < total_chunks:
        return jsonify({"status": "chunk_received", "next_chunk_index": meta["received_chunks"]})

    # Last chunk: hand the assembled file to the same code path a normal
    # single-shot upload uses (versioning, quota, checksum, mime type).
    try:
        node = _finalize_chunked_upload(parent, filename, data_path)
    finally:
        meta_path.unlink(missing_ok=True)
        data_path.unlink(missing_ok=True)

    return jsonify({"status": "complete", "node_id": str(node.id)})


def _finalize_chunked_upload(parent: Node, filename: str, data_path) -> Node:
    import mimetypes

    max_bytes = InstanceSettings.get_singleton().max_upload_mb * 1024 * 1024
    existing = Node.query.filter_by(parent_id=parent.id, name=filename, is_trashed=False).first()
    node = existing or Node(owner_id=current_user.id, parent_id=parent.id, type="file", name=filename)
    is_new = existing is None
    if is_new:
        db.session.add(node)
    db.session.flush()

    try:
        check_user_quota(current_user, max_bytes)
        if not is_new:
            _snapshot_previous_version(node)
        with open(data_path, "rb") as handle:
            stat = current_app.config["STORAGE"].save(node.id, handle, max_bytes)
    except StorageError as exc:
        db.session.rollback()
        abort(400, str(exc))

    delta = stat.size_bytes - (0 if is_new else node.size_bytes)
    node.size_bytes = stat.size_bytes
    node.checksum_sha256 = stat.checksum_sha256
    node.mime_type = mimetypes.guess_type(filename)[0]
    apply_usage_delta(current_user, delta)
    db.session.commit()
    activity.record("upload", user_id=current_user.id, node_id=node.id)
    jobs.enqueue_virus_scan(node.id)
    return node
