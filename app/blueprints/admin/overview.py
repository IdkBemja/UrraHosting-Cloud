from __future__ import annotations

from flask import render_template
from sqlalchemy import func

from . import bp
from ...blueprints.auth.decorators import admin_required
from ...extensions import db
from ...models.activity_log import ActivityLog
from ...models.instance_settings import InstanceSettings
from ...models.node import Node
from ...models.user import User


@bp.route("/")
@admin_required
def index():
    settings = InstanceSettings.get_singleton()
    user_count = db.session.query(func.count(User.id)).scalar() or 0
    file_count = db.session.query(func.count(Node.id)).filter(Node.type == "file", Node.is_trashed.is_(False)).scalar() or 0
    used_bytes = db.session.query(func.coalesce(func.sum(User.storage_used_bytes), 0)).scalar() or 0
    recent_activity = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(20).all()

    return render_template(
        "admin/overview.html",
        settings=settings,
        user_count=user_count,
        file_count=file_count,
        used_bytes=used_bytes,
        recent_activity=recent_activity,
    )
