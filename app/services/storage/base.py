from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO


class StorageError(ValueError):
    pass


@dataclass
class FileStat:
    size_bytes: int
    checksum_sha256: str


class StorageBackend(ABC):
    """Blob storage abstraction (plan.md section 3). Content is always
    addressed by an internal, system-generated id (a `Node.id` for the
    current version or a `FileVersion.id` for a past one) - never by a
    user-supplied name or path. This is what keeps the security surface
    small: nothing derived from user input ever becomes a filesystem
    path component.

    `LocalFsBackend` is the only implementation for the MVP (plan.md
    section 3 decision). An `S3Backend` can be added later for instances
    that need to scale `app`/`webdav` horizontally without a shared
    filesystem, without touching any caller of this interface.
    """

    @abstractmethod
    def save(self, blob_id: uuid.UUID, stream: BinaryIO, max_bytes: int) -> FileStat:
        """Write `stream` atomically under `blob_id`, enforcing
        `max_bytes` while reading (raises StorageError if exceeded).
        Returns the final size and sha256 checksum.
        """

    @abstractmethod
    def open(self, blob_id: uuid.UUID) -> BinaryIO:
        """Open a blob for reading. Raises StorageError if missing."""

    @abstractmethod
    def delete(self, blob_id: uuid.UUID) -> None:
        """Delete a blob if present; a no-op if it doesn't exist."""

    @abstractmethod
    def save_version(self, node_id: uuid.UUID, version_id: uuid.UUID, stream: BinaryIO, max_bytes: int) -> FileStat:
        """Same as `save`, but stores the blob under a node's version
        history instead of the live blob namespace.
        """

    @abstractmethod
    def open_version(self, node_id: uuid.UUID, version_id: uuid.UUID) -> BinaryIO:
        pass

    @abstractmethod
    def delete_version(self, node_id: uuid.UUID, version_id: uuid.UUID) -> None:
        pass
