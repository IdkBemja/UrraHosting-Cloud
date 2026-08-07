"""Storage backend tests - adapted from UrraHosting-WebPanel's
`tests/` suite for path-safety, but scoped to the id-addressed blob
scheme (see app/services/storage/local_fs.py and plan.md section 3).
Pure filesystem tests: no Flask app or DB needed.
"""

from __future__ import annotations

import io
import uuid

import pytest

from app.services.storage.base import StorageError
from app.services.storage.local_fs import LocalFsBackend


@pytest.fixture
def backend(tmp_path):
    return LocalFsBackend(blobs_root=tmp_path / "blobs", versions_root=tmp_path / "versions")


def test_save_and_open_roundtrip(backend):
    blob_id = uuid.uuid4()
    stat = backend.save(blob_id, io.BytesIO(b"hello world"), max_bytes=1024)

    assert stat.size_bytes == 11
    with backend.open(blob_id) as handle:
        assert handle.read() == b"hello world"


def test_open_missing_blob_raises(backend):
    with pytest.raises(StorageError):
        backend.open(uuid.uuid4())


def test_save_enforces_max_bytes_and_leaves_no_partial_file(backend, tmp_path):
    blob_id = uuid.uuid4()
    with pytest.raises(StorageError):
        backend.save(blob_id, io.BytesIO(b"x" * 100), max_bytes=10)

    with pytest.raises(StorageError):
        backend.open(blob_id)
    # No stray .part file left behind in the shard directory.
    shard = tmp_path / "blobs" / str(blob_id)[:2]
    leftovers = list(shard.glob("*")) if shard.exists() else []
    assert leftovers == []


def test_overwrite_replaces_content(backend):
    blob_id = uuid.uuid4()
    backend.save(blob_id, io.BytesIO(b"first"), max_bytes=1024)
    backend.save(blob_id, io.BytesIO(b"second version"), max_bytes=1024)

    with backend.open(blob_id) as handle:
        assert handle.read() == b"second version"


def test_delete_is_idempotent(backend):
    blob_id = uuid.uuid4()
    backend.save(blob_id, io.BytesIO(b"data"), max_bytes=1024)
    backend.delete(blob_id)
    backend.delete(blob_id)  # deleting again must not raise

    with pytest.raises(StorageError):
        backend.open(blob_id)


def test_versions_are_isolated_from_live_blob(backend):
    node_id = uuid.uuid4()
    version_id = uuid.uuid4()
    backend.save(node_id, io.BytesIO(b"live content"), max_bytes=1024)
    backend.save_version(node_id, version_id, io.BytesIO(b"old content"), max_bytes=1024)

    with backend.open(node_id) as handle:
        assert handle.read() == b"live content"
    with backend.open_version(node_id, version_id) as handle:
        assert handle.read() == b"old content"

    backend.delete_version(node_id, version_id)
    with backend.open(node_id) as handle:
        assert handle.read() == b"live content"  # unaffected by version deletion
