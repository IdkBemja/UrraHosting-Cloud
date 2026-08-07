"""Unauthenticated share-link viewer (plan.md section 5.2). A visitor
with a valid token can browse/download a file or folder without an
account - password-protected links additionally require the password
once per browser session, remembered via the signed Flask session
cookie (never as a query/form param on every subsequent link, which
would otherwise leak the password into browser history, proxy/server
logs and the Referer header sent to any file served from here).
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template, request, send_file, session

from ...extensions import db
from ...models.node import Node
from ...services import activity, sharing
from ...services.storage.base import StorageError

bp = Blueprint("public", __name__, url_prefix="/s")


def _session_key(token: str) -> str:
    return f"share_auth:{token}"


def _resolve_node_in_share(share, root: Node, sub_path: str) -> Node | None:
    if not sub_path:
        return root
    current = root
    for part in [p for p in sub_path.split("/") if p]:
        current = Node.query.filter_by(parent_id=current.id, name=part, is_trashed=False).first()
        if current is None:
            return None
    return current


@bp.route("/<token>", defaults={"sub_path": ""}, methods=["GET", "POST"])
@bp.route("/<token>/<path:sub_path>", methods=["GET", "POST"])
def view_share(token: str, sub_path: str):
    share = sharing.get_link_share_by_token(token)
    if share is None:
        abort(404)

    root = db.session.get(Node, share.node_id)
    if root is None or root.is_trashed:
        abort(404)

    if share.password_hash is not None and not session.get(_session_key(token)):
        if request.method == "POST":
            if sharing.check_link_password(share, request.form.get("password", "")):
                session[_session_key(token)] = True
            else:
                return render_template("public/password.html", token=token, sub_path=sub_path, error=True)
        else:
            return render_template("public/password.html", token=token, sub_path=sub_path, error=False)

    node = _resolve_node_in_share(share, root, sub_path)
    if node is None:
        abort(404)

    if node.type == "file":
        if node.is_quarantined:
            abort(403)
        try:
            handle = current_app.config["STORAGE"].open(node.id)
        except StorageError:
            abort(404)
        activity.record("download", node_id=node.id)
        return send_file(
            handle,
            mimetype=node.mime_type or "application/octet-stream",
            as_attachment=True,
            download_name=node.name,
        )

    children = Node.query.filter_by(parent_id=node.id, is_trashed=False).order_by(Node.type.desc(), Node.name.asc()).all()
    return render_template(
        "public/browse.html",
        token=token,
        sub_path=sub_path,
        folder=node,
        is_root=(node.id == root.id),
        children=children,
        permission=share.permission,
    )
