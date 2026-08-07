"""Thin wrapper around RQ enqueueing so request handlers (drive routes,
chunked_upload, webdav_app) don't each need to know how to build a Redis
connection/Queue - one place to change if the queue name or connection
strategy ever changes.
"""

from __future__ import annotations

import uuid

from flask import current_app
from redis import Redis
from rq import Queue

_queue: Queue | None = None


def _get_queue() -> Queue:
    global _queue
    if _queue is None:
        redis_url = current_app.config["INSTANCE"].redis_url
        _queue = Queue("default", connection=Redis.from_url(redis_url))
    return _queue


def enqueue_virus_scan(node_id: uuid.UUID) -> None:
    """No-op (not even an enqueue) when CLAMAV_HOST isn't configured, so
    instances that don't use antivirus scanning don't pay for a Redis
    round-trip on every upload for a job that would immediately no-op
    anyway (see worker/tasks.py::scan_node_for_virus's own check too -
    this is a fast-path, not the only guard).
    """
    if not current_app.config["INSTANCE"].clamav_host:
        return
    _get_queue().enqueue("app.worker.tasks.scan_node_for_virus", node_id)
