"""Internal metrics endpoint (Fase 3, plan.md section 9): lets
UrraHosting-Dashboard poll aggregated usage for this instance (storage
used/total, user/file counts, active shares) without needing direct DB
access. Protected by a shared-secret header (same `ORCHESTRATOR_TOKEN`
already generated for this instance by the Dashboard's ServiceTemplate,
see scripts/seed_platform_stack_templates.py::seed_cloudstorage) instead
of a user session - this is service-to-service, not a logged-in user.

Not network-isolated the way WebPanel's orchestrator is (no separate
internal-only Docker network in this repo's compose.yml) - reachable on
the same `app` container/port as the public web UI, just token-gated.
Acceptable for a read-only aggregate-stats endpoint; revisit if this
service ever needs to expose something more sensitive than counts.
"""

from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from ..extensions import db
from ..models.instance_settings import InstanceSettings
from ..models.node import Node
from ..models.share import Share
from ..models.user import User

bp = Blueprint("internal", __name__, url_prefix="/internal")


def _token_is_valid() -> bool:
    expected = current_app.config["INSTANCE"].orchestrator_token
    supplied = request.headers.get("X-Internal-Token", "")
    return hmac.compare_digest(supplied, expected)


@bp.route("/metrics")
def metrics():
    if not _token_is_valid():
        return jsonify({"error": "unauthorized"}), 401

    settings = InstanceSettings.get_singleton()
    user_count = db.session.query(func.count(User.id)).scalar() or 0
    active_user_count = db.session.query(func.count(User.id)).filter(User.active.is_(True)).scalar() or 0
    file_count = (
        db.session.query(func.count(Node.id))
        .filter(Node.type == "file", Node.is_trashed.is_(False))
        .scalar()
        or 0
    )
    used_bytes = db.session.query(func.coalesce(func.sum(User.storage_used_bytes), 0)).scalar() or 0
    active_share_count = db.session.query(func.count(Share.id)).scalar() or 0
    quarantined_count = (
        db.session.query(func.count(Node.id)).filter(Node.is_quarantined.is_(True)).scalar() or 0
    )

    return jsonify(
        {
            "user_count": user_count,
            "active_user_count": active_user_count,
            "file_count": file_count,
            "storage_used_bytes": used_bytes,
            "storage_total_bytes": settings.total_quota_bytes,
            "active_share_count": active_share_count,
            "quarantined_file_count": quarantined_count,
        }
    )
