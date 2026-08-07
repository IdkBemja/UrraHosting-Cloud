from __future__ import annotations

import hashlib

from flask import Blueprint, Response

from ..services.theming import get_brand, render_theme_css

bp = Blueprint("theming", __name__)


@bp.route("/theme.css")
def theme_css():
    brand = get_brand()
    css = render_theme_css(brand)
    etag = hashlib.sha256((css + str(brand.updated_at)).encode("utf-8")).hexdigest()[:16]
    response = Response(css, mimetype="text/css")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response
