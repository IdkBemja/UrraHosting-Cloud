from __future__ import annotations

import os
import time

from flask import Flask, jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config.platform_config import load_from_environ

from .extensions import bcrypt, csrf, db, limiter, login_manager
from .services.errors import error_response, from_http_exception
from .services.storage import build_storage_backend
from .services.theming import theme_context

# Bumped by hand on release - not derived from git/package metadata.
APP_VERSION = "1.0.0-Stable"


def create_app() -> Flask:
    config, result = load_from_environ(os.environ)
    if config is None:
        raise RuntimeError("Configuracion de instancia invalida: " + "; ".join(result.errors))
    for warning in result.warnings:
        print(f"[cloud][warn] {warning}")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["INSTANCE"] = config

    # Same reasoning as UrraHosting-WebPanel: only trust exactly
    # TRUSTED_PROXY_COUNT hops of X-Forwarded-* (Traefik == 1). Trusting
    # an unbounded number of hops would let a client spoof its own IP and
    # defeat rate limiting.
    if config.trusted_proxy_count > 0:
        app.wsgi_app = ProxyFix(  # type: ignore[assignment]
            app.wsgi_app,
            x_for=config.trusted_proxy_count,
            x_proto=config.trusted_proxy_count,
            x_host=config.trusted_proxy_count,
        )

    app.config["SECRET_KEY"] = config.app_secret
    app.config["SQLALCHEMY_DATABASE_URI"] = config.database_url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = config.session_cookie_secure
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 12
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_mb * 1024 * 1024
    app.config["RATELIMIT_STORAGE_URI"] = config.redis_url

    db.init_app(app)
    csrf.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    data_dir = config.data_dir
    files_root = data_dir / "files"
    branding_root = data_dir / "branding"
    tmp_uploads_root = files_root / "tmp_uploads"
    for directory in (files_root, branding_root, tmp_uploads_root):
        directory.mkdir(parents=True, exist_ok=True)

    app.config["STORAGE"] = build_storage_backend(config, files_root=files_root)
    app.config["BRANDING_DIR"] = branding_root
    app.config["TMP_UPLOADS_DIR"] = tmp_uploads_root

    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, user_id)

    from .blueprints.auth import bp as auth_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.drive import bp as drive_bp
    from .blueprints.public import bp as public_bp
    from .blueprints.theming import bp as theming_bp
    from .blueprints.internal import bp as internal_bp
    from .blueprints.sso import bp as sso_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(drive_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(theming_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(sso_bp)

    _install_security_headers(app, config)

    # Every abort()/raised HTTPException in the app funnels through here
    # instead of Werkzeug's raw default pages (see services/errors.py for
    # the copy and the public-share-link special case).
    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def handle_http_error(error):
        return from_http_exception(error)

    @app.errorhandler(500)
    def handle_server_error(error):
        # Never surface `error`'s own description/stack info here - unlike
        # the codes above, a 500 can carry internal exception details.
        return error_response(500)

    @app.context_processor
    def inject_globals():
        return {
            "current_year": time.strftime("%Y", time.gmtime()),
            "onlyoffice_enabled": bool(config.onlyoffice_server_url),
            "app_version": APP_VERSION,
            **theme_context(),
        }

    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.route("/")
    def index():
        # No blueprint owns bare "/" (drive is mounted at /drive, auth at
        # /login) - without this, visiting the instance's root domain 404s
        # even though the app is healthy. drive.my_drive is @login_required,
        # so this naturally bounces anonymous visitors to auth.login (via
        # login_manager.login_view) and takes logged-in users straight to
        # their drive root.
        return redirect(url_for("drive.my_drive"))

    @app.before_request
    def sync_max_upload_from_instance_settings():
        # InstanceSettings.max_upload_mb is editable from the Admin Panel
        # without a redeploy (app/blueprints/admin/storage.py); Flask reads
        # MAX_CONTENT_LENGTH fresh from app.config on every request (it's
        # not frozen at boot), so updating it here is enough to make a
        # raised/lowered limit take effect immediately - not just the
        # explicit max_bytes checks in drive/webdav upload code.
        from .models.instance_settings import InstanceSettings

        try:
            settings = InstanceSettings.query.first()
        except Exception:
            settings = None  # not migrated/seeded yet (e.g. during app.cli migrate's own app_context)
        if settings is not None:
            app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024

    _EXEMPT_2FA_ENDPOINTS = {
        "auth.login", "auth.login_2fa", "auth.logout",
        "drive.setup_2fa", "drive.confirm_2fa",
        "static", "theming.theme_css", "healthz",
    }

    @app.before_request
    def enforce_2fa_policy():
        # Fase 3 "2FA obligatorio por politica": when the owner turns this
        # on (Admin Panel > Almacenamiento > "Forzar 2FA"), every admin/
        # owner account without 2FA already configured gets redirected to
        # setup on their very next request instead of just having a
        # hidden nag in the UI - the request is actually blocked, not
        # just discouraged.
        from flask_login import current_user

        from .models.instance_settings import InstanceSettings

        if request.endpoint in _EXEMPT_2FA_ENDPOINTS:
            return None
        if not current_user.is_authenticated or not current_user.is_admin or current_user.totp_enabled:
            return None
        try:
            settings = InstanceSettings.query.first()
        except Exception:
            return None
        if settings is not None and settings.enforce_2fa_for_admins:
            return redirect(url_for("drive.setup_2fa"))
        return None

    return app


def _install_security_headers(app: Flask, config) -> None:
    # Dark/light mode is resolved server-side (the `data-theme` attribute
    # is rendered directly on <html> from the logged-in user's
    # `theme_mode`, see templates/base.html), so there is no need for an
    # inline flash-of-wrong-theme script, and no inline <script> tags or
    # onclick=/onsubmit= handlers are used anywhere (see static/js/
    # confirm.js and chunked-upload.js for how those are avoided) -
    # CSP stays as strict as WebPanel's for all of that.
    #
    # 'unsafe-eval' IS required despite the above: Alpine.js's standard
    # build (static/vendor/alpine.min.js) evaluates x-data/@click/:class
    # expressions via `new Function(...)`, which needs 'unsafe-eval' by
    # design (there's a separate Alpine "CSP build" with a restricted,
    # eval-free expression parser, but it disallows some of the plain-JS
    # ternaries/method calls this app's templates already use in
    # branding.html/browse.html - switching would mean rewriting those).
    # script-src otherwise stays locked to 'self' (no external hosts), so
    # this only widens what same-origin script can do, not where it can
    # come from.
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval'; "
        "style-src 'self'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    @app.after_request
    def set_security_headers(response):
        response_csp = csp
        if request.endpoint == "drive.edit_document" and config.onlyoffice_server_url:
            # Only this one page needs to load OnlyOffice's api.js from
            # an external origin and embed its editor in an iframe -
            # every other page keeps the fully locked-down default CSP
            # above. Scoped by endpoint instead of loosening script-src/
            # frame-src globally for a feature only this route uses.
            origin = config.onlyoffice_server_url.rstrip("/")
            response_csp = (
                f"default-src 'self'; script-src 'self' 'unsafe-eval' {origin}; "
                f"style-src 'self'; font-src 'self'; img-src 'self' data:; "
                f"connect-src 'self' {origin}; frame-src {origin}; object-src 'none'; "
                f"base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )
        response.headers["Content-Security-Policy"] = response_csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        if config.session_cookie_secure:
            # No includeSubDomains, same reasoning as WebPanel: this
            # instance is reachable both under the shared platform base
            # domain and under whatever custom domain a client points at
            # it later; pinning HSTS platform-wide would poison unrelated
            # tenants/subdomains.
            response.headers["Strict-Transport-Security"] = "max-age=63072000"
        return response


app = create_app()
