from __future__ import annotations

from flask import render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ...models.node import Node

_MAX_RESULTS = 100


@bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results: list[Node] = []
    if query:
        results = (
            Node.query.filter(
                Node.owner_id == current_user.id,
                Node.is_trashed.is_(False),
                Node.search_vector.op("@@")(func.plainto_tsquery("simple", query)),
            )
            .order_by(Node.type.desc(), Node.name.asc())
            .limit(_MAX_RESULTS)
            .all()
        )
    return render_template("drive/search.html", query=query, results=results)
