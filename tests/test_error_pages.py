"""Branded error pages (app/services/errors.py): every abort()/raised
HTTPException must render `errors/generic.html` with Spanish copy -
never Werkzeug's raw English default text - and a 404 raised inside the
public share viewer (`blueprints/public`, url_prefix `/s`) must show the
"link revoked/expired" message instead of a generic 404, since that is
the only reason that blueprint ever 404s.
"""

from __future__ import annotations

import pathlib

import pytest
from flask import Blueprint, Flask, abort
from flask_wtf.csrf import CSRFError

from app.services.errors import error_response, from_http_exception

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


@pytest.fixture
def error_app():
    flask_app = Flask(
        "error_pages_test",
        template_folder=str(APP_DIR / "templates"),
        static_folder=str(APP_DIR / "static"),
    )
    flask_app.config["SECRET_KEY"] = "test"

    @flask_app.context_processor
    def inject_globals():
        return {
            "app_name": "Test Cloud",
            "logo_url": "/static/branding/urrahosting-default-logo.svg",
            "favicon_url": "/static/branding/urrahosting-default-favicon.svg",
            "theme_mode": "light",
            "current_year": "2026",
        }

    theming_bp = Blueprint("theming", __name__)

    @theming_bp.route("/theme.css")
    def theme_css():
        return "", 200

    @flask_app.route("/")
    def index():
        return "home"

    public_bp = Blueprint("public", __name__, url_prefix="/s")

    @public_bp.route("/<token>")
    def view_share(token):
        abort(404)

    drive_bp = Blueprint("drive", __name__, url_prefix="/drive")

    @drive_bp.route("/missing")
    def missing():
        abort(404)

    @drive_bp.route("/quarantined")
    def quarantined():
        abort(403)

    @drive_bp.route("/infected")
    def infected():
        abort(403, "Este archivo fue marcado como potencialmente malicioso por el escaneo antivirus")

    @drive_bp.route("/csrf-fail")
    def csrf_fail():
        raise CSRFError("The CSRF tokens do not match.")

    flask_app.register_blueprint(theming_bp)
    flask_app.register_blueprint(public_bp)
    flask_app.register_blueprint(drive_bp)

    @flask_app.errorhandler(400)
    @flask_app.errorhandler(403)
    @flask_app.errorhandler(404)
    @flask_app.errorhandler(409)
    @flask_app.errorhandler(413)
    @flask_app.errorhandler(429)
    def handle_http_error(error):
        return from_http_exception(error)

    @flask_app.errorhandler(500)
    def handle_server_error(error):
        return error_response(500)

    return flask_app


def test_revoked_share_link_shows_branded_message(error_app):
    resp = error_app.test_client().get("/s/does-not-exist")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 404
    assert "Hubo un error por nuestra parte" in body
    assert "revocó" in body and "expiró" in body
    assert "The requested URL was not found" not in body


def test_generic_404_outside_public_blueprint_uses_default_copy(error_app):
    resp = error_app.test_client().get("/drive/missing")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 404
    assert "Página no encontrada" in body
    assert "Hubo un error por nuestra parte" not in body
    assert "The requested URL was not found" not in body


def test_bare_403_uses_generic_spanish_copy_not_werkzeug_default(error_app):
    resp = error_app.test_client().get("/drive/quarantined")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 403
    assert "No tienes permiso para acceder a este contenido." in body
    assert "You don't have the permission" not in body


def test_custom_abort_description_is_preserved(error_app):
    resp = error_app.test_client().get("/drive/infected")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 403
    assert "potencialmente malicioso" in body


def test_csrf_error_shows_generic_spanish_copy_not_english_reason(error_app):
    resp = error_app.test_client().get("/drive/csrf-fail")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 400
    assert "Solicitud inválida" in body
    assert "CSRF tokens do not match" not in body


def test_error_response_lets_caller_override_title_and_message(error_app):
    with error_app.test_request_context("/"):
        html, status = error_response(404, title="Titulo custom", message="Mensaje custom")

    assert status == 404
    assert "Titulo custom" in html
    assert "Mensaje custom" in html
