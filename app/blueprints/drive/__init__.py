from flask import Blueprint

bp = Blueprint("drive", __name__, url_prefix="/drive")

from . import routes, sharing, settings, search, versions, chunked_upload, twofactor, onlyoffice  # noqa: E402,F401
