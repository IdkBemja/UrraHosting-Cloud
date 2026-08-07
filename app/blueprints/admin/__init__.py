from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import overview, users, branding, files, shares, storage  # noqa: E402,F401  (register routes on import)
