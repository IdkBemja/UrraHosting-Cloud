"""S3-compatible `StorageBackend` (Fase 3, plan.md section 3/9): the
pluggable alternative to `LocalFsBackend` for instances that need to run
`app`/`webdav` as more than one replica without a shared filesystem.
Selected via `STORAGE_BACKEND=s3` (see config/platform_config.py) -
works against AWS S3 or any S3-compatible endpoint (MinIO, etc.) by
pointing `S3_ENDPOINT_URL` at it.

Same id-addressed-blob contract as LocalFsBackend (never a user-supplied
name/path as an object key), just backed by S3 objects instead of local
files:
    blobs/<id>.bin
    versions/<node_id>/<version_id>.bin

Note on verification: this class is implemented against the documented
boto3 API and mirrors LocalFsBackend's contract exactly (same method
signatures, same hashing-while-uploading approach), but - unlike
LocalFsBackend, which was exercised against a real Postgres-free sqlite
smoke test in this session - it has not been run against a live S3/MinIO
endpoint. Treat it as reviewed-but-unverified until it's been used
against a real bucket at least once.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from typing import BinaryIO

from .base import FileStat, StorageBackend, StorageError

_CHUNK = 1024 * 1024


def _hash_and_buffer(stream: BinaryIO, max_bytes: int) -> tuple[tempfile.SpooledTemporaryFile, FileStat]:
    buffer = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    digest = hashlib.sha256()
    written = 0
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        written += len(chunk)
        if written > max_bytes:
            buffer.close()
            raise StorageError("El archivo excede el tamano maximo permitido")
        digest.update(chunk)
        buffer.write(chunk)
    buffer.seek(0)
    return buffer, FileStat(size_bytes=written, checksum_sha256=digest.hexdigest())


class S3Backend(StorageBackend):
    def __init__(self, *, bucket: str, endpoint_url: str | None, access_key: str, secret_key: str, region: str):
        import boto3  # deferred import: only instances that opt into STORAGE_BACKEND=s3 need it installed

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def _blob_key(self, blob_id: uuid.UUID) -> str:
        return f"blobs/{blob_id}.bin"

    def _version_key(self, node_id: uuid.UUID, version_id: uuid.UUID) -> str:
        return f"versions/{node_id}/{version_id}.bin"

    def _put(self, key: str, stream: BinaryIO, max_bytes: int) -> FileStat:
        buffer, stat = _hash_and_buffer(stream, max_bytes)
        try:
            self._client.upload_fileobj(buffer, self._bucket, key)
        finally:
            buffer.close()
        return stat

    def _get(self, key: str) -> BinaryIO:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise StorageError("Archivo no encontrado") from exc
        return response["Body"]

    def _delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def save(self, blob_id: uuid.UUID, stream: BinaryIO, max_bytes: int) -> FileStat:
        return self._put(self._blob_key(blob_id), stream, max_bytes)

    def open(self, blob_id: uuid.UUID) -> BinaryIO:
        return self._get(self._blob_key(blob_id))

    def delete(self, blob_id: uuid.UUID) -> None:
        self._delete(self._blob_key(blob_id))

    def save_version(self, node_id: uuid.UUID, version_id: uuid.UUID, stream: BinaryIO, max_bytes: int) -> FileStat:
        return self._put(self._version_key(node_id, version_id), stream, max_bytes)

    def open_version(self, node_id: uuid.UUID, version_id: uuid.UUID) -> BinaryIO:
        return self._get(self._version_key(node_id, version_id))

    def delete_version(self, node_id: uuid.UUID, version_id: uuid.UUID) -> None:
        self._delete(self._version_key(node_id, version_id))
