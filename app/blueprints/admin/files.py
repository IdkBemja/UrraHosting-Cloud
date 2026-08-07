from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from . import bp
from ...blueprints.auth.decorators import admin_required
from ...extensions import db
from ...models.node import Node
from ...models.user import User
from ...services import activity
from ...services.nodes import delete_node_tree

_PAGE_SIZE = 50


@bp.route("/files")
@admin_required
def list_files():
    query = request.args.get("q", "").strip()
    owner_filter = request.args.get("owner", "").strip()
    page = request.args.get("page", 1, type=int)

    q = Node.query.filter(Node.is_trashed.is_(False))
    if query:
        q = q.filter(Node.name.ilike(f"%{query}%"))
    if owner_filter:
        q = q.join(User, User.id == Node.owner_id).filter(User.username.ilike(owner_filter))

    total = q.count()
    nodes = (
        q.order_by(Node.created_at.desc())
        .offset((page - 1) * _PAGE_SIZE)
        .limit(_PAGE_SIZE)
        .all()
    )
    return render_template(
        "admin/files.html",
        nodes=nodes,
        query=query,
        owner_filter=owner_filter,
        page=page,
        total=total,
        page_size=_PAGE_SIZE,
    )


@bp.route("/files/<uuid:node_id>/delete", methods=["POST"])
@admin_required
def delete_file(node_id):
    """Moderation action: permanently removes content that violates the
    instance's usage policy - unlike the Drive App's own trash flow, this
    is a hard delete straight past the papelera (an admin removing abusive
    content shouldn't leave it recoverable by the uploader).
    """
    node = Node.query.filter_by(id=node_id).first()
    if node is None:
        return redirect(url_for("admin.list_files"))
    delete_node_tree(current_app.config["STORAGE"], node)
    db.session.commit()
    activity.record("admin_deleted_content", user_id=current_user.id)
    flash("Elemento eliminado permanentemente", "success")
    return redirect(url_for("admin.list_files"))
