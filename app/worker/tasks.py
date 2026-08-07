"""Background maintenance + on-demand jobs. Each function assumes it's
called from inside a Flask app context (see `worker_main.py` for the
periodic scheduler, `services/jobs.py` for on-demand enqueueing from
request handlers) and commits its own work - RQ jobs are one-shot
functions, not long-lived request handlers.

Thumbnail generation / search indexing beyond the Postgres tsvector
already in place (app/models/node.py::search_vector) remain out of
scope - intentionally not stubbed out with fake logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..extensions import db
from ..models.file_version import FileVersion
from ..models.instance_settings import InstanceSettings
from ..models.node import Node
from ..models.user import User
from ..services.nodes import delete_node_tree
from . import antivirus


def purge_expired_trash(storage) -> int:
    """Permanently deletes trashed nodes older than
    `InstanceSettings.trash_retention_days`. Only processes top-level
    trashed nodes (parent not itself trashed, or parent missing) since
    `delete_node_tree` already recurses into every descendant - visiting
    an already-trashed descendant a second time here would just be
    wasted queries.
    """
    settings = InstanceSettings.get_singleton()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.trash_retention_days)

    candidates = Node.query.filter(Node.is_trashed.is_(True), Node.trashed_at < cutoff).all()
    trashed_ids = {n.id for n in candidates}
    purged = 0
    for node in candidates:
        if node.parent_id in trashed_ids:
            continue  # will be purged as part of its trashed ancestor
        delete_node_tree(storage, node)
        purged += 1
    db.session.commit()
    return purged


def purge_old_versions(storage) -> int:
    """Keeps only the most recent `version_retention_count` versions per
    file node, deleting the rest (both the DB row and the blob).
    """
    settings = InstanceSettings.get_singleton()
    keep = settings.version_retention_count

    node_ids = [row[0] for row in db.session.query(FileVersion.node_id).distinct()]
    purged = 0
    for node_id in node_ids:
        versions = (
            FileVersion.query.filter_by(node_id=node_id)
            .order_by(FileVersion.created_at.desc())
            .all()
        )
        for old in versions[keep:]:
            storage.delete_version(node_id, old.id)
            db.session.delete(old)
            purged += 1
    db.session.commit()
    return purged


def recalculate_storage_for_all_users() -> int:
    """Drift-correction job: `User.storage_used_bytes` is normally kept
    in sync incrementally on every upload/delete (see
    services/quota.py::apply_usage_delta), but this recomputes it from
    the source of truth (`nodes.size_bytes`) in case of a missed update
    or a crash mid-transaction.
    """
    rows = (
        db.session.query(Node.owner_id, func.coalesce(func.sum(Node.size_bytes), 0))
        .filter(Node.type == "file", Node.is_trashed.is_(False))
        .group_by(Node.owner_id)
        .all()
    )
    usage_by_owner = dict(rows)
    updated = 0
    for user in User.query.all():
        real_usage = usage_by_owner.get(user.id, 0)
        if user.storage_used_bytes != real_usage:
            user.storage_used_bytes = real_usage
            updated += 1
    db.session.commit()
    return updated


def scan_node_for_virus(node_id) -> str:
    """Enqueued after every upload/overwrite when CLAMAV_HOST is
    configured (see services/jobs.py::enqueue_virus_scan and its call
    sites in drive/routes.py, chunked_upload.py, webdav_app.py). A
    missing/unreachable clamd is treated as "scan skipped", not as
    grounds to quarantine the file - antivirus is defense in depth here,
    not the only thing standing between an upload and being served.
    """
    from flask import current_app

    config = current_app.config["INSTANCE"]
    if not config.clamav_host:
        return "skipped_not_configured"

    node = db.session.get(Node, node_id)
    if node is None or node.type != "file":
        return "skipped_not_found"

    storage = current_app.config["STORAGE"]
    try:
        with storage.open(node.id) as stream:
            infected, detail = antivirus.scan_stream(config.clamav_host, config.clamav_port, stream)
    except antivirus.AntivirusUnavailable as exc:
        print(f"[worker][warn] {exc}")
        return "skipped_unavailable"

    node.is_quarantined = infected
    db.session.commit()
    if infected:
        print(f"[worker][warn] node {node_id} quarantined: {detail}")
    return "infected" if infected else "clean"
