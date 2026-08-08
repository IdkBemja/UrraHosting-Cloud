from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Computed, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db

NODE_TYPES = ("file", "folder")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Node(db.Model):
    """Unified file/folder tree (Google-Drive style): a single self
    referencing table instead of separate files/folders tables, so
    move/rename/breadcrumbs are plain UPDATE/JOIN queries on `parent_id`.

    The on-disk blob for a file node lives at
    `${DATA_DIR}/files/blobs/<id[:2]>/<id>.bin`, addressed by `id`
    (see app/services/storage) - `name` here is metadata only and never
    touches the filesystem path, which is what makes path-traversal a
    non-issue for the tree itself (WebDAV still has to translate DAV path
    segments to node ids via the queries below).

    Every user gets exactly one `parent_id IS NULL` folder node created at
    signup (their drive root, see services/nodes.py::create_user_root).
    The (parent_id, name) partial unique index below is intentionally a
    no-op for parent_id IS NULL rows (Postgres never treats NULL = NULL
    for uniqueness), which is fine because that row is created exactly
    once per user by application code, not by user-facing "create" calls.
    """

    __tablename__ = "nodes"
    __table_args__ = (
        # Partial unique index: only ACTIVE (non-trashed) siblings must
        # have distinct names. Trashed items keep their old name even if
        # a new item reuses it later.
        Index(
            "ix_nodes_parent_name_active",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=db.text("is_trashed = false"),
        ),
        Index("ix_nodes_owner_parent", "owner_id", "parent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"), nullable=True)
    type: Mapped[str] = mapped_column(Enum(*NODE_TYPES, name="node_type"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(db.BigInteger, nullable=False, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fase 3: set by the optional ClamAV scan (app/worker/antivirus.py)
    # when a file's content matches a known signature. Quarantined files
    # are blocked from download/preview/WebDAV read (see the checks in
    # drive/routes.py, sharing.py and webdav_app.py) but kept, not
    # deleted, so an admin can review/purge them deliberately.
    is_quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    # Postgres STORED generated column (migrations/versions/0002_search_vector.py)
    # - recomputed by Postgres itself from `name` on every write, never
    # assigned from Python. `Computed(...)` must mirror the migration's
    # expression exactly: it's what tells SQLAlchemy to omit this column
    # from INSERT/UPDATE entirely. Without it, SQLAlchemy still sends an
    # explicit NULL for any unset nullable column with no Python-side
    # default, which Postgres rejects for a GENERATED ALWAYS column.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', coalesce(name, ''))", persisted=True), nullable=True
    )

    owner: Mapped["User"] = relationship(back_populates="nodes", foreign_keys=[owner_id])
    parent: Mapped["Node | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Node"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    versions: Mapped[list["FileVersion"]] = relationship(back_populates="node", cascade="all, delete-orphan")
    shares: Mapped[list["Share"]] = relationship(back_populates="node", cascade="all, delete-orphan")

    @property
    def is_folder(self) -> bool:
        return self.type == "folder"

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Node {self.name} ({self.type})>"
