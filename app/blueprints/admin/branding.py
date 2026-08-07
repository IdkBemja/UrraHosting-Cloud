from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from . import bp
from ...blueprints.auth.decorators import owner_required
from ...extensions import db
from ...models.brand_settings import (
    DEFAULT_ACCENT,
    DEFAULT_APP_NAME,
    DEFAULT_DARK,
    DEFAULT_LIGHT,
    DEFAULT_PRESET,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
    BrandSettings,
)
from ...services.theming import get_brand

_ALLOWED_IMAGE_EXTENSIONS = {"svg", "png", "webp"}
_MAX_IMAGE_BYTES = 2 * 1024 * 1024

PRESETS = {
    "urrahosting": {
        "label": "UrraHosting Theme (por defecto)",
        "primary": DEFAULT_PRIMARY,
        "secondary": DEFAULT_SECONDARY,
        "accent": DEFAULT_ACCENT,
        "dark": DEFAULT_DARK,
        "light": DEFAULT_LIGHT,
    },
    "indigo": {
        "label": "Indigo",
        "primary": "#4f46e5",
        "secondary": "#4338ca",
        "accent": "#a855f7",
        "dark": "#1e1b2e",
        "light": "#f5f6fb",
    },
    "forest": {
        "label": "Verde bosque",
        "primary": "#15803d",
        "secondary": "#166534",
        "accent": "#84cc16",
        "dark": "#0f1a12",
        "light": "#f4faf5",
    },
    "custom": {"label": "Personalizado"},
}


@bp.route("/branding")
@owner_required
def edit_branding():
    brand = get_brand()
    return render_template("admin/branding.html", brand=brand, presets=PRESETS)


@bp.route("/branding", methods=["POST"])
@owner_required
def update_branding():
    brand = get_brand()
    preset = request.form.get("theme_preset", DEFAULT_PRESET)

    brand.app_name = request.form.get("app_name", "").strip() or DEFAULT_APP_NAME
    brand.theme_preset = preset
    brand.supports_dark_mode = request.form.get("supports_dark_mode") == "on"
    brand.dark_mode_default = request.form.get("dark_mode_default") == "on"

    if preset in PRESETS and preset != "custom":
        p = PRESETS[preset]
        brand.primary, brand.secondary, brand.accent = p["primary"], p["secondary"], p["accent"]
        brand.dark, brand.light = p["dark"], p["light"]
    else:
        brand.primary = request.form.get("primary", brand.primary)
        brand.secondary = request.form.get("secondary", brand.secondary)
        brand.accent = request.form.get("accent", brand.accent)
        brand.dark = request.form.get("dark", brand.dark)
        brand.light = request.form.get("light", brand.light)

    _handle_upload("logo", brand, "logo_url")
    _handle_upload("favicon", brand, "favicon_url")

    if request.form.get("reset_logo") == "on":
        brand.logo_url = None
    if request.form.get("reset_favicon") == "on":
        brand.favicon_url = None

    db.session.commit()
    flash("Marca actualizada", "success")
    return redirect(url_for("admin.edit_branding"))


def _handle_upload(field_name: str, brand: BrandSettings, attr: str) -> None:
    upload = request.files.get(field_name)
    if not upload or not upload.filename:
        return

    filename = secure_filename(upload.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        flash(f"Formato de {field_name} no permitido (usa svg, png o webp)", "error")
        return

    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > _MAX_IMAGE_BYTES:
        flash(f"El archivo de {field_name} excede 2MB", "error")
        return

    branding_dir = current_app.config["BRANDING_DIR"]
    stored_name = f"{field_name}.{ext}"
    upload.save(branding_dir / stored_name)
    setattr(brand, attr, f"/admin/branding/asset/{stored_name}")


@bp.route("/branding/asset/<path:filename>")
def branding_asset(filename: str):
    from flask import send_from_directory

    safe_name = secure_filename(filename)
    if safe_name != filename:
        from flask import abort

        abort(404)
    return send_from_directory(current_app.config["BRANDING_DIR"], safe_name)
