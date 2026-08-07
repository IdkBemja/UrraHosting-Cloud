from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...models.node import Node
from ...models.share import PERMISSIONS, Share
from ...models.user import User
from ...services import activity, sharing
from ...services.storage.base import StorageError


def _get_owned_node(node_id: uuid.UUID) -> Node:
    node = Node.query.filter_by(id=node_id, owner_id=current_user.id, is_trashed=False).first()
    if node is None:
        abort(404)
    return node


@bp.route("/share/<uuid:node_id>")
@login_required
def share_node(node_id):
    node = _get_owned_node(node_id)
    return render_template("drive/share.html", node=node, shares=node.shares)


@bp.route("/share/<uuid:node_id>/link", methods=["POST"])
@login_required
def create_link(node_id):
    node = _get_owned_node(node_id)
    permission = request.form.get("permission", "viewer")
    if permission not in PERMISSIONS:
        permission = "viewer"
    password = request.form.get("password", "").strip() or None

    expires_at = None
    expires_in_days = request.form.get("expires_in_days", type=int)
    if expires_in_days and expires_in_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    sharing.create_link_share(node, current_user.id, permission=permission, password=password, expires_at=expires_at)
    db.session.commit()
    activity.record("share_created", user_id=current_user.id, node_id=node.id)
    flash("Link de compartición creado", "success")
    return redirect(url_for("drive.share_node", node_id=node.id))


@bp.route("/share/<uuid:node_id>/user", methods=["POST"])
@login_required
def create_with_user(node_id):
    node = _get_owned_node(node_id)
    identifier = request.form.get("username", "").strip()
    permission = request.form.get("permission", "viewer")
    if permission not in PERMISSIONS:
        permission = "viewer"

    target = User.query.filter(
        (User.username.ilike(identifier)) | (User.email.ilike(identifier))
    ).first()
    if target is None:
        flash(f"No existe ningun usuario '{identifier}' en esta instancia", "error")
        return redirect(url_for("drive.share_node", node_id=node.id))
    if target.id == current_user.id:
        flash("No puedes compartir un elemento contigo mismo", "error")
        return redirect(url_for("drive.share_node", node_id=node.id))

    sharing.create_user_share(node, current_user.id, target.id, permission=permission)
    db.session.commit()
    activity.record("share_created", user_id=current_user.id, node_id=node.id)
    flash(f"Compartido con '{target.username}'", "success")
    return redirect(url_for("drive.share_node", node_id=node.id))


@bp.route("/share/revoke/<uuid:share_id>", methods=["POST"])
@login_required
def revoke(share_id):
    share = Share.query.filter_by(id=share_id).first()
    if share is None or share.created_by != current_user.id:
        abort(404)
    node_id = share.node_id
    sharing.revoke_share(share)
    db.session.commit()
    activity.record("share_revoked", user_id=current_user.id, node_id=node_id)
    flash("Compartición revocada", "success")
    return redirect(url_for("drive.share_node", node_id=node_id))


@bp.route("/shared-by-me")
@login_required
def shared_by_me():
    shares = sharing.list_shared_by_me(current_user.id)
    return render_template("drive/shared_by_me.html", shares=shares)


@bp.route("/shared-with-me")
@login_required
def shared_with_me():
    shares = sharing.list_shared_with_me(current_user.id)
    return render_template("drive/shared_with_me.html", shares=shares)


@bp.route("/shared/<uuid:node_id>")
@login_required
def browse_shared(node_id):
    """Browse/download a node current_user doesn't own but has access to
    via a Share (direct, or inherited from an ancestor folder) - separate
    from `browse()`/`download()` because ownership no longer gates access,
    the Share does.
    """
    node = Node.query.filter_by(id=node_id, is_trashed=False).first()
    if node is None:
        abort(404)
    governing = sharing.find_governing_share(node, user_id=current_user.id)
    if governing is None:
        abort(404)
    share, _root = governing

    if node.type == "file":
        if node.is_quarantined:
            abort(403, "Este archivo fue marcado como potencialmente malicioso por el escaneo antivirus")
        try:
            handle = current_app.config["STORAGE"].open(node.id)
        except StorageError:
            abort(404)
        activity.record("download", user_id=current_user.id, node_id=node.id)
        return send_file(handle, mimetype=node.mime_type or "application/octet-stream", as_attachment=True, download_name=node.name)

    children = Node.query.filter_by(parent_id=node.id, is_trashed=False).order_by(Node.type.desc(), Node.name.asc()).all()
    return render_template(
        "drive/browse_shared.html",
        folder=node,
        children=children,
        permission=share.permission,
    )
