from .base import FileStat, StorageBackend, StorageError
from .local_fs import LocalFsBackend


def build_storage_backend(config, *, files_root):
    """Factory picking the StorageBackend implementation from
    `config.storage_backend` (plan.md section 3/9 Fase 3) - the only
    place that needs to know both implementations exist. `S3Backend`
    imports boto3 lazily inside its own __init__, so choosing 'local'
    never requires boto3 to even be importable.
    """
    if config.storage_backend == "s3":
        from .s3_backend import S3Backend

        return S3Backend(
            bucket=config.s3_bucket,
            endpoint_url=config.s3_endpoint_url,
            access_key=config.s3_access_key,
            secret_key=config.s3_secret_key,
            region=config.s3_region,
        )
    return LocalFsBackend(
        blobs_root=files_root / "blobs",
        versions_root=files_root / "versions",
    )


__all__ = ["FileStat", "StorageBackend", "StorageError", "LocalFsBackend", "build_storage_backend"]
