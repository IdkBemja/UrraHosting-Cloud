"""WebDAV entrypoint (separate `webdav` container, see compose.yml) so
UrraHosting-Cloud can be mounted as a network drive
("Conectar a unidad de red" on Windows, "Connect to Server" on
macOS/Linux). Ported design notes (plan.md section 5.2/6):

  - Authentication uses `AppPassword` (scope='webdav'), never the user's
    main login password/2FA (Nextcloud pattern) - see
    CloudDomainController.basic_auth_user below.
  - The DAV tree is NOT a second copy of the filesystem: every DAV path
    segment is resolved against the same `nodes` table the Drive App
    uses (services/nodes.py::resolve_path), and file content is read/
    written through the same StorageBackend (id-addressed blobs). A file
    renamed over WebDAV and one renamed in the browser are the exact
    same underlying row/blob.

Runs under gunicorn as its own WSGI callable (`app.webdav_app:app`), on
`WEBDAV_PORT`, routed by Traefik at `/dav` (see compose.traefik.yml).
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone

from wsgidav.wsgidav_app import WsgiDAVApp  # noqa: I001 - must import before wsgidav.dav_error
                                             # (wsgidav.dav_error <-> wsgidav.util are mutually
                                             # importing internally; importing wsgidav_app first
                                             # forces the package to finish initializing in the
                                             # order it actually expects, avoiding a
                                             # "partially initialized module" ImportError).
from wsgidav.dav_error import HTTP_FORBIDDEN, HTTP_INSUFFICIENT_STORAGE, DAVError
from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider
from wsgidav.dc.base_dc import BaseDomainController

from .extensions import bcrypt, db
from .main import create_app
from .models.app_password import AppPassword
from .models.instance_settings import InstanceSettings
from .models.node import Node
from .models.user import User
from .services import jobs
from .services.nodes import delete_node_tree, resolve_path
from .services.quota import apply_usage_delta, check_user_quota
from .services.storage.base import StorageError

_flask_app = create_app()

# Reused as-is (not reimplemented) so a file overwritten over WebDAV gets
# the exact same version-snapshot behavior as one overwritten through the
# Drive App's own upload endpoint - see that function's docstring.
from .blueprints.drive.routes import _snapshot_previous_version  # noqa: E402


def _split_path(path: str) -> list[str]:
    return [p for p in path.strip("/").split("/") if p]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CloudDomainController(BaseDomainController):
    def get_domain_realm(self, path_info, environ):
        return "UrraHosting Cloud"

    def require_authentication(self, realm, environ):
        return True

    def supports_http_digest_auth(self):
        # Digest auth needs the plain password (or an MD5 of it) at
        # verification time; AppPassword only stores a bcrypt hash, same
        # tradeoff WebPanel/Dashboard make elsewhere. Basic auth over TLS
        # (Traefik terminates TLS in front of this service) is
        # equivalent in practice and is what every mainstream WebDAV
        # client (Windows, macOS, rclone) defaults to anyway.
        return False

    def basic_auth_user(self, realm, user_name, password, environ):
        user = User.query.filter(
            (User.username.ilike(user_name)) | (User.email.ilike(user_name))
        ).first()
        if user is None or not user.active:
            return False

        candidates = AppPassword.query.filter_by(
            user_id=user.id, scope="webdav", revoked_at=None
        ).all()
        for candidate in candidates:
            if bcrypt.check_password_hash(candidate.password_hash, password):
                candidate.last_used_at = _now()
                db.session.commit()
                environ["cloud.user_id"] = str(user.id)
                return True
        return False


class _DeferCloseWrapper:
    """Forwards writes to a SpooledTemporaryFile but swallows close() -
    see the comment in CloudFileResource.begin_write for why."""

    def __init__(self, target):
        self._target = target

    def write(self, data):
        return self._target.write(data)

    def writelines(self, lines):
        return self._target.writelines(lines)

    def close(self):
        pass


class CloudFileResource(DAVNonCollection):
    def __init__(self, path: str, environ: dict, node: Node):
        super().__init__(path, environ)
        self.node = node

    def get_content_length(self):
        return self.node.size_bytes

    def get_content_type(self):
        return self.node.mime_type or "application/octet-stream"

    def get_creation_date(self):
        return self.node.created_at.timestamp()

    def get_last_modified(self):
        return self.node.updated_at.timestamp()

    def get_etag(self):
        return self.node.checksum_sha256 or f'"{self.node.id}-{self.node.size_bytes}"'

    def support_etag(self):
        return True

    def get_content(self):
        if self.node.is_quarantined:
            raise DAVError(HTTP_FORBIDDEN)
        try:
            return _flask_app.config["STORAGE"].open(self.node.id)
        except StorageError as exc:
            raise DAVError(HTTP_FORBIDDEN) from exc

    def begin_write(self, *, content_type=None):
        # Buffered to a spooled tempfile (memory up to 8MB, then disk) so
        # StorageBackend.save() - which needs a seekable/readable stream
        # to hash+size+write atomically - gets one regardless of how the
        # DAV client streams the PUT body.
        #
        # request_server.py's do_PUT calls `fileobj.close()` right after
        # writing the body, *before* calling end_write() (see its source:
        # it treats end_write purely as a notification hook, assuming a
        # typical provider already persisted everything to a real file
        # that survives close()). We still need to read the buffered
        # bytes back in end_write() to hash+store them, so begin_write
        # returns a thin wrapper whose close() is a no-op and defers the
        # real close to `end_write` below, once we're done reading it.
        self._tmp = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        return _DeferCloseWrapper(self._tmp)

    def end_write(self, *, with_errors):
        if with_errors:
            self._tmp.close()
            return
        self._tmp.seek(0)
        max_bytes = InstanceSettings.get_singleton().max_upload_mb * 1024 * 1024
        owner = self.node.owner
        old_size = self.node.size_bytes
        try:
            check_user_quota(owner, max_bytes)
            if old_size or self.node.checksum_sha256:
                # Same versioning behavior as the Drive App's own upload
                # endpoint - a PUT over WebDAV that overwrites an existing
                # file must not silently discard the previous content.
                _snapshot_previous_version(self.node)
            stat = _flask_app.config["STORAGE"].save(self.node.id, self._tmp, max_bytes)
        except StorageError as exc:
            self._tmp.close()
            raise DAVError(HTTP_INSUFFICIENT_STORAGE) from exc
        finally:
            self._tmp.close()

        self.node.size_bytes = stat.size_bytes
        self.node.checksum_sha256 = stat.checksum_sha256
        apply_usage_delta(owner, stat.size_bytes - old_size)
        db.session.commit()
        jobs.enqueue_virus_scan(self.node.id)

    def delete(self):
        delete_node_tree(_flask_app.config["STORAGE"], self.node)
        db.session.commit()

    def support_recursive_move(self, dest_path):
        return True

    def move_recursive(self, dest_path):
        _move_node(self.node, dest_path)


class CloudFolderResource(DAVCollection):
    def __init__(self, path: str, environ: dict, node: Node):
        super().__init__(path, environ)
        self.node = node

    def get_creation_date(self):
        return self.node.created_at.timestamp()

    def get_last_modified(self):
        return self.node.updated_at.timestamp()

    def get_used_bytes(self) -> int | None:
        # RFC 4331 quota-used-bytes/quota-available-bytes - this is what
        # Windows Explorer's "X GB free of Y GB" gauge reads for a mapped
        # WebDAV drive. Reused from the same per-user accounting the Drive
        # App and quota checks use (app/services/quota.py), not disk usage
        # of the underlying container - the instance's own filesystem free
        # space is irrelevant to a tenant's plan quota.
        return self.node.owner.storage_used_bytes

    def get_available_bytes(self) -> int | None:
        return self.node.owner.storage_available_bytes

    def get_member_names(self):
        children = Node.query.filter_by(parent_id=self.node.id, is_trashed=False).all()
        return [child.name for child in children]

    def get_member(self, name):
        child = Node.query.filter_by(parent_id=self.node.id, name=name, is_trashed=False).first()
        if child is None:
            return None
        child_path = f"{self.path.rstrip('/')}/{name}"
        if child.type == "folder":
            return CloudFolderResource(child_path, self.environ, child)
        return CloudFileResource(child_path, self.environ, child)

    def create_collection(self, name):
        folder = Node(owner_id=self.node.owner_id, parent_id=self.node.id, type="folder", name=name)
        db.session.add(folder)
        db.session.commit()
        return CloudFolderResource(f"{self.path.rstrip('/')}/{name}", self.environ, folder)

    def create_empty_resource(self, name):
        node = Node(owner_id=self.node.owner_id, parent_id=self.node.id, type="file", name=name, size_bytes=0)
        db.session.add(node)
        db.session.commit()
        return CloudFileResource(f"{self.path.rstrip('/')}/{name}", self.environ, node)

    def support_recursive_delete(self):
        return True

    def delete(self):
        delete_node_tree(_flask_app.config["STORAGE"], self.node)
        db.session.commit()

    def support_recursive_move(self, dest_path):
        return True

    def move_recursive(self, dest_path):
        _move_node(self.node, dest_path)


def _move_node(node: Node, dest_path: str) -> None:
    """MOVE just rewrites `parent_id`/`name` in the `nodes` table - no
    filesystem rename needed, since blobs are addressed by node id, not
    by path (see plan.md section 3 "refinamiento de diseno").
    """
    parts = _split_path(dest_path)
    if not parts:
        raise DAVError(HTTP_FORBIDDEN)
    new_name, parent_parts = parts[-1], parts[:-1]
    owner = node.owner
    new_parent = resolve_path(owner, parent_parts)
    if new_parent is None or new_parent.type != "folder":
        raise DAVError(HTTP_FORBIDDEN)
    node.parent_id = new_parent.id
    node.name = new_name
    db.session.commit()


class CloudDAVProvider(DAVProvider):
    def get_resource_inst(self, path: str, environ: dict):
        user_id = environ.get("cloud.user_id")
        if not user_id:
            return None
        user = db.session.get(User, uuid.UUID(user_id))
        if user is None:
            return None

        node = resolve_path(user, _split_path(path))
        if node is None:
            return None
        if node.type == "folder":
            return CloudFolderResource(path, environ, node)
        return CloudFileResource(path, environ, node)


class _AppContextMiddleware:
    """Wraps every WebDAV request in a Flask application context so
    Flask-SQLAlchemy's scoped session works inside the provider/resource
    classes above exactly like it does in the `app` (web) container.

    WsgiDAV's own `ErrorPrinter.__call__` (innermost middleware in the
    chain built by `WsgiDAVApp`) is itself a generator function (it
    `yield`s response chunks) - calling it only builds a generator
    object without running any of its body, including the GET/PROPFIND/
    PUT handling that needs the DB. If this wrapper did
    `with app.app_context(): return self._wsgi_app(...)`, the `with`
    block would exit (popping the context) the instant that unstarted
    generator was returned, and the actual work would then run with NO
    app context once the WSGI server (or a test client) iterates it
    afterwards - which is exactly the "working outside of application
    context" failure this construction avoids: making `__call__` itself
    a generator via `yield from` keeps the `with` block (and therefore
    the app context) alive for as long as the caller keeps pulling
    chunks from it.
    """

    def __init__(self, wsgi_app, flask_app):
        self._wsgi_app = wsgi_app
        self._flask_app = flask_app

    def __call__(self, environ, start_response):
        with self._flask_app.app_context():
            app_iter = self._wsgi_app(environ, start_response)
            try:
                yield from app_iter
            finally:
                if hasattr(app_iter, "close"):
                    app_iter.close()


_dav_config = {
    "provider_mapping": {"/dav": CloudDAVProvider()},
    "http_authenticator": {
        "domain_controller": CloudDomainController,
        "accept_basic": True,
        "accept_digest": False,
        "default_to_digest": False,
    },
    "verbose": 1,
    "logging": {"enable_loggers": []},
    "dir_browser": {"enable": False},
}

app = _AppContextMiddleware(WsgiDAVApp(_dav_config), _flask_app)
