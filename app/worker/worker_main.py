"""Entrypoint for the `worker` container (see compose.yml). Runs an RQ
worker (for on-demand jobs enqueued by the `app`/`webdav` containers,
Fase 2: thumbnails, search indexing) plus a simple interval-based
scheduler thread for the periodic housekeeping jobs in tasks.py -
deliberately not a full cron/APScheduler dependency for the MVP, just a
sleep loop enqueuing jobs onto the same Redis queue the RQ worker drains.
"""

from __future__ import annotations

import threading
import time

import redis
from rq import Queue, Worker

from ..main import create_app
from . import tasks

_MAINTENANCE_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


def _run_maintenance_once(app) -> None:
    with app.app_context():
        storage = app.config["STORAGE"]
        purged_trash = tasks.purge_expired_trash(storage)
        purged_versions = tasks.purge_old_versions(storage)
        updated_users = tasks.recalculate_storage_for_all_users()
        print(
            f"[worker] maintenance: purged_trash={purged_trash} "
            f"purged_versions={purged_versions} recalculated_users={updated_users}"
        )


def _maintenance_loop(app) -> None:
    while True:
        try:
            _run_maintenance_once(app)
        except Exception as exc:  # pragma: no cover - defensive: one bad cycle must not kill the loop
            print(f"[worker][error] maintenance cycle failed: {exc!r}")
        time.sleep(_MAINTENANCE_INTERVAL_SECONDS)


def main() -> None:
    app = create_app()
    redis_conn = redis.from_url(app.config["INSTANCE"].redis_url)

    scheduler_thread = threading.Thread(target=_maintenance_loop, args=(app,), daemon=True)
    scheduler_thread.start()

    with app.app_context():
        queue = Queue("default", connection=redis_conn)
        worker = Worker([queue], connection=redis_conn)
        worker.work()


if __name__ == "__main__":
    main()
