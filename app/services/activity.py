from __future__ import annotations

import uuid

from flask import request

from ..extensions import db
from ..models.activity_log import ActivityLog


def record(action: str, *, user_id: uuid.UUID | None = None, node_id: uuid.UUID | None = None) -> None:
    entry = ActivityLog(
        user_id=user_id,
        action=action,
        node_id=node_id,
        ip=request.remote_addr if request else None,
        user_agent=request.headers.get("User-Agent", "")[:255] if request else None,
    )
    db.session.add(entry)
    db.session.commit()
