"""Collaborative document editing via an external OnlyOffice Document
Server (Fase 4, plan.md section 9/11). Entirely opt-in: hidden unless
`ONLYOFFICE_SERVER_URL` is configured, and no such server ships in this
repo's compose.yml - the operator provisions it separately and points
this app at it.

Verification note (same posture as S3Backend/antivirus): implemented
against OnlyOffice's documented Document Server API (config shape,
callback status codes 0-7) but not exercised against a live Document
Server in this session - no instance was available. Treat as reviewed-
but-unverified until run against a real server at least once.

Three moving pieces, none of which use the browser session cookie for
the Document Server <-> this app leg (the Document Server has no login
of its own here) - both use short-lived HS256 JWTs signed with this
instance's own APP_SECRET instead:
  - GET  /drive/edit/<node_id>            (browser, needs login)
  - GET  /drive/onlyoffice-fetch/<id>      (Document Server -> us, token in URL)
  - POST /drive/onlyoffice-callback/<id>   (Document Server -> us, token in URL)
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
import uuid

import jwt as pyjwt
from flask import abort, current_app, jsonify, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...services import jobs
from ...services.quota import apply_usage_delta, check_user_quota
from ...services.storage.base import StorageError
from .routes import _get_owned_file, _snapshot_previous_version

_DOCUMENT_TYPES = {
    "word": {"doc", "docx", "odt", "rtf", "txt"},
    "cell": {"xls", "xlsx", "ods", "csv"},
    "slide": {"ppt", "pptx", "odp"},
}
_FETCH_TOKEN_TTL_SECONDS = 300


def _document_type(extension: str) -> str | None:
    for doc_type, extensions in _DOCUMENT_TYPES.items():
        if extension in extensions:
            return doc_type
    return None


def _mint_internal_token(node_id: uuid.UUID, purpose: str) -> str:
    secret = current_app.config["INSTANCE"].app_secret
    payload = {"node_id": str(node_id), "purpose": purpose, "exp": int(time.time()) + _FETCH_TOKEN_TTL_SECONDS}
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _verify_internal_token(token: str, node_id: uuid.UUID, purpose: str) -> bool:
    secret = current_app.config["INSTANCE"].app_secret
    try:
        claims = pyjwt.decode(token, secret, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        return False
    return claims.get("node_id") == str(node_id) and claims.get("purpose") == purpose


@bp.route("/edit/<uuid:node_id>")
@login_required
def edit_document(node_id):
    config = current_app.config["INSTANCE"]
    if not config.onlyoffice_server_url:
        abort(404)

    node = _get_owned_file(node_id)
    if node.is_quarantined:
        abort(403)
    extension = node.name.rsplit(".", 1)[-1].lower() if "." in node.name else ""
    doc_type = _document_type(extension)
    if doc_type is None:
        abort(400, "Este tipo de archivo no se puede editar en linea")

    fetch_token = _mint_internal_token(node.id, "fetch")
    callback_token = _mint_internal_token(node.id, "callback")

    editor_config = {
        "document": {
            "fileType": extension,
            # Changing the key on every edit session (not just every
            # save) forces Document Server to treat this as a fresh
            # editing session rather than resuming a cached one - the
            # checksum already changes whenever the content changes, and
            # we fall back to updated_at for a node that has no checksum
            # yet (freshly created, still empty).
            "key": f"{node.id}-{node.checksum_sha256 or node.updated_at.timestamp()}",
            "title": node.name,
            "url": url_for("drive.onlyoffice_fetch", node_id=node.id, token=fetch_token, _external=True),
        },
        "documentType": doc_type,
        "editorConfig": {
            "callbackUrl": url_for(
                "drive.onlyoffice_callback", node_id=node.id, token=callback_token, _external=True
            ),
            "user": {"id": str(current_user.id), "name": current_user.username},
        },
    }
    if config.onlyoffice_jwt_secret:
        editor_config["token"] = pyjwt.encode(editor_config, config.onlyoffice_jwt_secret, algorithm="HS256")

    return render_template(
        "drive/edit_document.html",
        node=node,
        onlyoffice_server_url=config.onlyoffice_server_url.rstrip("/"),
        editor_config=editor_config,
    )


@bp.route("/onlyoffice-fetch/<uuid:node_id>")
def onlyoffice_fetch(node_id):
    """Called by the Document Server itself (no browser session) to read
    the current content - guarded by the short-lived token instead of
    @login_required.
    """
    if not _verify_internal_token(request.args.get("token", ""), node_id, "fetch"):
        abort(403)
    from ...models.node import Node

    node = Node.query.filter_by(id=node_id, is_trashed=False, type="file").first()
    if node is None or node.is_quarantined:
        abort(404)
    try:
        handle = current_app.config["STORAGE"].open(node.id)
    except StorageError:
        abort(404)
    return send_file(handle, mimetype=node.mime_type or "application/octet-stream", download_name=node.name)


@bp.route("/onlyoffice-callback/<uuid:node_id>", methods=["POST"])
def onlyoffice_callback(node_id):
    """Document Server's save notification. Status codes per its API:
    0=no doc, 1=being edited, 2=ready for saving, 3=save error,
    4=closed with no changes, 6=force-saved, 7=force-save error. Only 2
    and 6 carry a `url` to download the new content from.
    """
    if not _verify_internal_token(request.args.get("token", ""), node_id, "callback"):
        abort(403)
    from ...models.node import Node

    node = Node.query.filter_by(id=node_id, is_trashed=False, type="file").first()
    if node is None:
        return jsonify({"error": 0})  # nothing to save against; still ack per protocol

    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in (2, 6):
        return jsonify({"error": 0})

    download_url = body.get("url")
    if not download_url:
        return jsonify({"error": 1})

    max_bytes = current_app.config["INSTANCE"].max_upload_mb * 1024 * 1024
    owner = node.owner
    old_size = node.size_bytes
    try:
        check_user_quota(owner, max_bytes)
        _snapshot_previous_version(node)
        with urllib.request.urlopen(download_url, timeout=30) as response:  # noqa: S310 - server-configured OnlyOffice URL, not user input
            stat = current_app.config["STORAGE"].save(node.id, response, max_bytes)
    except (StorageError, urllib.error.URLError) as exc:
        db.session.rollback()
        current_app.logger.warning("OnlyOffice callback save failed for %s: %s", node_id, exc)
        return jsonify({"error": 1})

    node.size_bytes = stat.size_bytes
    node.checksum_sha256 = stat.checksum_sha256
    apply_usage_delta(owner, stat.size_bytes - old_size)
    db.session.commit()
    jobs.enqueue_virus_scan(node.id)
    return jsonify({"error": 0})
