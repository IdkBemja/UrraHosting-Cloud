from __future__ import annotations

from flask import flash, redirect, render_template, url_for

from . import bp
from ...blueprints.auth.decorators import admin_required
from ...extensions import db
from ...models.share import Share
from ...services import activity, sharing


@bp.route("/shares")
@admin_required
def list_shares():
    all_shares = Share.query.order_by(Share.created_at.desc()).all()
    return render_template("admin/shares.html", shares=all_shares)


@bp.route("/shares/<uuid:share_id>/revoke", methods=["POST"])
@admin_required
def revoke_share(share_id):
    share = Share.query.filter_by(id=share_id).first()
    if share is not None:
        node_id = share.node_id
        sharing.revoke_share(share)
        db.session.commit()
        activity.record("admin_share_revoked", node_id=node_id)
        flash("Compartición revocada", "success")
    return redirect(url_for("admin.list_shares"))
