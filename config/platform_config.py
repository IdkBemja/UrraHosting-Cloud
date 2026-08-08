"""Typed loader/validator for the instance-level `.env` contract.

Mirrors the pattern used by UrraHosting-WebPanel's
`config/platform_config.py`: this is the ONLY module that reads
`os.environ` directly. Every other module receives a `PlatformConfig`
instance instead, so the contract can never drift between `app`,
`webdav` and `worker` (they all boot from the same loader).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_KNOWN_PLACEHOLDER_SECRETS = frozenset(
    {
        "cambia-esta-contraseña-unica",
        "cambia-este-secreto-largo-y-aleatorio-64-hex",
        "cambia-este-token-largo-y-aleatorio-64-hex",
        "cambia-esta-password-db",
        "admin",
        "password",
        "changeme",
        "change-me",
        "secret",
    }
)

_MIN_APP_SECRET_LENGTH = 32
_MIN_APP_PASSWORD_LENGTH = 10


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PlatformConfig:
    instance_id: str
    data_dir: Path

    app_port: int
    webdav_port: int
    public_base_domain: str
    traefik_public_network: str
    traefik_web_entrypoint: str
    traefik_cert_resolver: str
    trusted_proxy_count: int

    app_user: str
    app_password: str
    app_secret: str
    orchestrator_token: str

    database_url: str
    redis_url: str

    session_cookie_secure: bool
    debug: bool
    max_upload_mb: int
    instance_storage_gb: int
    default_user_quota_gb: int
    trash_retention_days: int
    version_retention_count: int

    # Fase 3: pluggable storage backend. 'local' (default) uses
    # LocalFsBackend against DATA_DIR; 'S3' targets any S3-compatible
    # endpoint (AWS S3, MinIO, etc.) via S3Backend - see
    # app/services/storage/s3_backend.py. The s3_* fields are only
    # required (and only validated) when storage_backend == 's3'.
    storage_backend: str
    s3_endpoint_url: str | None
    s3_bucket: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    s3_region: str

    # Fase 3: optional antivirus scanning of uploaded files via a clamd
    # daemon. None/unset means disabled - this is opt-in infrastructure
    # the operator must provision separately (no ClamAV container ships
    # in this repo's compose.yml), see app/worker/antivirus.py.
    clamav_host: str | None
    clamav_port: int

    # Fase 4: optional collaborative editing via an external OnlyOffice
    # Document Server (also opt-in infrastructure, not bundled in
    # compose.yml). None/unset means the "Editar" action is hidden - see
    # app/blueprints/drive/onlyoffice.py.
    onlyoffice_server_url: str | None
    onlyoffice_jwt_secret: str | None


def _get(environ: dict, name: str, default: str | None = None) -> str | None:
    value = environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _require_int(environ: dict, name: str, errors: list[str], *, minimum: int | None = None) -> int | None:
    raw = _get(environ, name)
    if raw is None:
        errors.append(f"Falta la variable obligatoria {name}")
        return None
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} debe ser un entero, recibido: {raw!r}")
        return None
    if minimum is not None and value < minimum:
        errors.append(f"{name} debe ser >= {minimum}")
        return None
    return value


def _require_str(environ: dict, name: str, errors: list[str]) -> str | None:
    value = _get(environ, name)
    if not value:
        errors.append(f"Falta la variable obligatoria {name}")
        return None
    return value


def _bool(environ: dict, name: str, default: bool) -> bool:
    raw = _get(environ, name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _check_secret(name: str, value: str | None, errors: list[str], *, minimum: int) -> None:
    if value and (len(value) < minimum or value.strip().lower() in _KNOWN_PLACEHOLDER_SECRETS):
        errors.append(
            f"{name} es demasiado corto o es un valor de ejemplo; usa al menos {minimum} "
            "caracteres aleatorios (python -c \"import secrets; print(secrets.token_hex(32))\")"
        )


def load_from_environ(environ: dict) -> tuple[PlatformConfig | None, ValidationResult]:
    result = ValidationResult()

    instance_id = _require_str(environ, "INSTANCE_ID", result.errors)
    data_dir_raw = _require_str(environ, "DATA_DIR", result.errors)
    app_port = _require_int(environ, "APP_PORT", result.errors, minimum=1)
    webdav_port = _require_int(environ, "WEBDAV_PORT", result.errors, minimum=1)
    app_user = _require_str(environ, "APP_USER", result.errors)
    app_password = _require_str(environ, "APP_PASSWORD", result.errors)
    app_secret = _require_str(environ, "APP_SECRET", result.errors)
    orchestrator_token = _require_str(environ, "ORCHESTRATOR_TOKEN", result.errors)
    database_url = _require_str(environ, "DATABASE_URL", result.errors)
    redis_url = _require_str(environ, "REDIS_URL", result.errors)
    max_upload_mb = _require_int(environ, "MAX_UPLOAD_MB", result.errors, minimum=1)
    instance_storage_gb = _require_int(environ, "INSTANCE_STORAGE_GB", result.errors, minimum=1)
    default_user_quota_gb = _require_int(environ, "DEFAULT_USER_QUOTA_GB", result.errors, minimum=1)
    trash_retention_days = _require_int(environ, "TRASH_RETENTION_DAYS", result.errors, minimum=1)
    version_retention_count = _require_int(environ, "VERSION_RETENTION_COUNT", result.errors, minimum=1)

    if app_port is not None and webdav_port is not None and app_port == webdav_port:
        result.errors.append("APP_PORT y WEBDAV_PORT no pueden ser el mismo puerto")

    _check_secret("APP_SECRET", app_secret, result.errors, minimum=_MIN_APP_SECRET_LENGTH)
    _check_secret("ORCHESTRATOR_TOKEN", orchestrator_token, result.errors, minimum=_MIN_APP_SECRET_LENGTH)
    _check_secret("APP_PASSWORD", app_password, result.errors, minimum=_MIN_APP_PASSWORD_LENGTH)

    if app_user and app_user.strip().lower() in {"root", "administrator", "admin"}:
        result.warnings.append(f"APP_USER='{app_user}' es un nombre de usuario predecible")

    trusted_proxy_count = _require_int(environ, "TRUSTED_PROXY_COUNT", [], minimum=0) or 1
    session_cookie_secure = _bool(environ, "SESSION_COOKIE_SECURE", True)
    if not session_cookie_secure:
        result.warnings.append("SESSION_COOKIE_SECURE=false expone la cookie de sesión sin HTTPS; solo usar en desarrollo local")

    debug = _bool(environ, "DEBUG", False)
    if debug:
        result.warnings.append("DEBUG=true no debe usarse en produccion")

    storage_backend = (_get(environ, "STORAGE_BACKEND", "local") or "local").strip().lower()
    if storage_backend not in ("local", "s3"):
        result.errors.append(f"STORAGE_BACKEND debe ser 'local' o 's3', recibido: {storage_backend!r}")
    s3_bucket = _get(environ, "S3_BUCKET")
    s3_access_key = _get(environ, "S3_ACCESS_KEY")
    s3_secret_key = _get(environ, "S3_SECRET_KEY")
    if storage_backend == "s3":
        for name, value in (("S3_BUCKET", s3_bucket), ("S3_ACCESS_KEY", s3_access_key), ("S3_SECRET_KEY", s3_secret_key)):
            if not value:
                result.errors.append(f"STORAGE_BACKEND=s3 requiere {name}")

    clamav_host = _get(environ, "CLAMAV_HOST")
    clamav_port = _require_int(environ, "CLAMAV_PORT", [], minimum=1) or 3310

    onlyoffice_server_url = _get(environ, "ONLYOFFICE_SERVER_URL")
    onlyoffice_jwt_secret = _get(environ, "ONLYOFFICE_JWT_SECRET")

    if not result.ok:
        return None, result

    config = PlatformConfig(
        instance_id=instance_id,
        data_dir=Path(data_dir_raw),
        app_port=app_port,
        webdav_port=webdav_port,
        public_base_domain=_get(environ, "PUBLIC_BASE_DOMAIN", "") or "",
        traefik_public_network=_get(environ, "TRAEFIK_PUBLIC_NETWORK", "traefik-public") or "traefik-public",
        traefik_web_entrypoint=_get(environ, "TRAEFIK_WEB_ENTRYPOINT", "websecure") or "websecure",
        traefik_cert_resolver=_get(environ, "TRAEFIK_CERT_RESOLVER", "letsencrypt") or "letsencrypt",
        trusted_proxy_count=trusted_proxy_count,
        app_user=app_user,
        app_password=app_password,
        app_secret=app_secret,
        orchestrator_token=orchestrator_token,
        database_url=database_url,
        redis_url=redis_url,
        session_cookie_secure=session_cookie_secure,
        debug=debug,
        max_upload_mb=max_upload_mb,
        instance_storage_gb=instance_storage_gb,
        default_user_quota_gb=default_user_quota_gb,
        trash_retention_days=trash_retention_days,
        version_retention_count=version_retention_count,
        storage_backend=storage_backend,
        s3_endpoint_url=_get(environ, "S3_ENDPOINT_URL"),
        s3_bucket=s3_bucket,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        s3_region=_get(environ, "S3_REGION", "us-east-1") or "us-east-1",
        clamav_host=clamav_host,
        clamav_port=clamav_port,
        onlyoffice_server_url=onlyoffice_server_url,
        onlyoffice_jwt_secret=onlyoffice_jwt_secret,
    )
    return config, result


__all__ = ["PlatformConfig", "ValidationResult", "load_from_environ"]
