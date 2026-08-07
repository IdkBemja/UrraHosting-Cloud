# UrraHosting Cloud

Almacenamiento en la nube auto-hospedado (estilo Google Drive / Nextcloud) que se despliega como un servicio más del ecosistema UrraHosting, usando el mismo mecanismo `platform_stack` con el que hoy se despliegan WebPanel o GamePanel desde **UrraHosting**.

Cada instancia desplegada es multi-usuario (owner/admin/member), tiene su propio panel administrativo, su propia base de datos y volumen de archivos, y expone el contenido tanto por web como por **WebDAV** para poder montarlo como unidad de red en Windows/macOS/Linux.

## Características

- **Mi unidad**: subir/descargar archivos y carpetas (con subida por chunks/resumable para archivos grandes), previsualización inline (imágenes/PDF/texto), búsqueda full-text, versionado (restaurar versiones anteriores), papelera con restaurar/purgar (cascada real a subcarpetas).
- **Comparticiones**: links públicos (con contraseña y/o expiración opcional) y compartir con usuarios específicos de la instancia, heredado automáticamente a subcarpetas.
- **Edición colaborativa** (opcional): integración con OnlyOffice Document Server para editar documentos ofimáticos en el navegador.
- **Panel administrativo**: resumen, gestión de usuarios (cuotas, activar/suspender), explorador de archivos cross-usuario, gestión de comparticiones activas, ajustes de almacenamiento (cuotas/retención/extensiones permitidas, editables sin redeploy), marca (nombre, logo, colores, modo oscuro).
- **Seguridad**: CSRF, rate limiting sobre Redis, 2FA (TOTP con códigos de recuperación, forzable por política para cuentas admin/owner), antivirus opcional (ClamAV) que pone en cuarentena archivos infectados, SSO real con el Dashboard vía JWT firmado con el secreto ya compartido de la instancia.
- **WebDAV**: montar la instancia como unidad de red real (Windows/macOS/Linux), con "app passwords" separadas de la contraseña principal (patrón Nextcloud) — nunca se usa la contraseña de login para clientes WebDAV/sync. Este es el mecanismo real de "cliente de escritorio"; no se construyó una app de escritorio nativa aparte (ver `plan.md` sección 12).
- **Almacenamiento pluggable**: filesystem local (default) o cualquier backend S3-compatible (AWS S3, MinIO) vía `STORAGE_BACKEND=s3`.
- **Theming en vivo**: `/theme.css` se genera dinámicamente desde la base de datos; cambiar colores/logo en el panel no requiere redeploy. Preset de fábrica **"UrraHosting Theme"** (paleta heredada del Dashboard) con fallback automático de logo/favicon si la instancia no tiene marca propia configurada.
- **Multi-tenant a nivel de infraestructura**: cada despliegue es una instancia Docker aislada (propia BD, propio volumen, propio subdominio vía Traefik), igual que WebPanel.

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Backend | Python 3.12, Flask 3, SQLAlchemy 2 + Alembic |
| Base de datos | PostgreSQL 16 |
| Cache / rate-limit / cola | Redis 7 |
| Frontend | Jinja2 + htmx + Alpine.js (sin bundler, vendorizado localmente) |
| WebDAV | WsgiDAV sobre gunicorn |
| Tareas en segundo plano | RQ |
| Contenedores | Docker Compose, Traefik (reverse proxy) |

## Estructura del proyecto

```
UrraHosting-Cloud/
├── app/
│   ├── main.py              # App factory (proceso "app": UI + API)
│   ├── webdav_app.py        # Entrypoint WSGI del proceso "webdav"
│   ├── cli.py                # `python -m app.cli migrate` (Alembic + seed inicial)
│   ├── extensions.py         # db, csrf, bcrypt, login_manager, limiter
│   ├── models/                # SQLAlchemy: users, nodes, shares, brand_settings, instance_settings...
│   ├── blueprints/
│   │   ├── auth/                # login/logout, 2FA en dos pasos, decoradores de rol
│   │   ├── admin/                 # overview, usuarios, archivos, comparticiones, marca, almacenamiento
│   │   ├── drive/                  # Mi unidad, papelera, comparticiones, versiones, busqueda,
│   │   │                           # settings/2FA/app-passwords, chunked upload, onlyoffice
│   │   ├── public/                # links de compartición públicos (/s/<token>)
│   │   ├── sso.py                  # SSO vía JWT compartido con el Dashboard
│   │   ├── internal.py             # /internal/metrics (token-gated, para el Dashboard)
│   │   └── theming.py               # /theme.css
│   ├── services/
│   │   ├── storage/                # StorageBackend + LocalFsBackend + S3Backend (blobs por id)
│   │   ├── nodes.py                  # árbol de archivos/carpetas, mover, purgar, cascada de papelera
│   │   ├── sharing.py, twofactor.py, jobs.py, quota.py, activity.py, theming.py
│   ├── worker/                # RQ worker: mantenimiento periódico + antivirus (clamd) bajo demanda
│   ├── templates/, static/
├── migrations/               # Alembic (3 revisiones)
├── scripts/                  # (la plantilla real vive en UrraHosting-Dashboard, ver mas abajo)
├── tests/                     # 15 tests multiplataforma + 6 Linux-only
├── compose.yml / compose.dev.yml / compose.traefik.yml
├── Dockerfile
└── .env.example
```

## Desarrollo local

Requisitos: Docker y Docker Compose.

```bash
cp .env.example .env
# Edita .env: APP_USER, APP_PASSWORD, APP_SECRET, ORCHESTRATOR_TOKEN, DB_PASSWORD
# (usa `python -c "import secrets; print(secrets.token_hex(32))"` para los secretos)

docker compose -f compose.yml -f compose.dev.yml up --build
```

Esto levanta `app` (puerto `APP_PORT`, por defecto 5000) y `webdav` (puerto `WEBDAV_PORT`, por defecto 5001) publicados directamente al host, más `db` (Postgres) y `redis`. El contenedor `app` corre `python -m app.cli migrate` en cada arranque (aplica migraciones y crea el owner inicial desde `APP_USER`/`APP_PASSWORD` si la base está vacía).

Login inicial: `http://localhost:5000/login` con las credenciales `APP_USER`/`APP_PASSWORD` del `.env`.

### Correr los tests

```bash
pip install -r requirements.txt pytest
pytest tests/
```

`tests/test_storage_local_fs.py` usa `os.O_DIRECTORY`/`dir_fd` (hardening anti path-traversal, ver `app/services/storage/local_fs.py`), que es exclusivo de Linux — no corre en Windows nativo, solo dentro del contenedor Docker. El resto (theming, cuotas, 2FA, protocolo antivirus) corre en cualquier plataforma.

## Variables de entorno

Ver [`.env.example`](./.env.example) para el contrato completo, validado por [`config/platform_config.py`](./config/platform_config.py) (falla rápido y explícito si falta algo o si un secreto es un valor de ejemplo conocido). Las variables marcadas como "system" en `UrraHosting-Dashboard/scripts/seed_platform_stack_templates.py::seed_cloudstorage` las inyecta automáticamente el Dashboard cuando esto se despliega como `platform_stack`; en desarrollo local se ponen a mano en `.env`.

Las integraciones opcionales de Fase 3/4 (`STORAGE_BACKEND=s3`, `CLAMAV_HOST`, `ONLYOFFICE_SERVER_URL`) quedan desactivadas si se dejan vacías — ninguna requiere infraestructura adicional para que el resto de la app funcione.

## Despliegue vía UrraHosting-Dashboard

Este repo está pensado para desplegarse como un `ServiceTemplate` de tipo `platform_stack` en **UrraHosting**, exactamente igual que WebPanel/GamePanel:

- `compose.yml` declara los 5 servicios fijos (`app`, `webdav`, `worker`, `db`, `redis`), sin publicar puertos al host — todo el tráfico entra por Traefik.
- `compose.traefik.yml` define las rutas: la web app en `cloud-<instance-id>.<dominio>` y WebDAV en el mismo dominio bajo `/dav`.

## Theming / white-label

El nombre, logo, favicon y paleta de colores de cada instancia son 100% configurables desde el panel administrativo (`/admin/branding`, solo `owner`). El preset de fábrica **"UrraHosting Theme"** usa la misma paleta que el Dashboard (`#e25822` / `#ff4500` / `#ff4081`) para que una instancia recién desplegada se sienta parte de la familia sin configuración adicional. Si la instancia no tiene logo/favicon propio, se sirve el default de UrraHosting — nunca queda una instancia sin marca visual. Detalle en `plan.md` sección 7.

## Licencia

Proyecto desarrollado por UrraHosting para UrraHosting SpA y Open Source.
