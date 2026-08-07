"""Theming engine: instance-level branding (name/logo/colors/dark mode)
resolved into the `/theme.css` stylesheet and into template globals.

Design decisions (plan.md section 7, confirmed 2026-08-07):
  - Default app name: "UrraHosting Cloud".
  - Default preset "UrraHosting Theme" mirrors the Dashboard's own
    palette (main.css) so a freshly deployed instance looks like part of
    the family without any admin action.
  - logo_url/favicon_url are nullable on BrandSettings; this module is
    the single place that resolves the fallback to the bundled
    UrraHosting default asset, so an instance can never end up rendering
    a broken <img> or a generic placeholder.
  - Dark mode is a first-class part of the engine, not just a user
    preference: `supports_dark_mode` (admin toggle) gates whether users
    even see a light/dark switch at all.
"""

from __future__ import annotations

from flask import url_for
from flask_login import current_user

from ..models.brand_settings import BrandSettings

DEFAULT_LOGO_STATIC = "branding/urrahosting-default-logo.svg"
DEFAULT_FAVICON_STATIC = "branding/urrahosting-default-favicon.svg"


def get_brand() -> BrandSettings:
    return BrandSettings.get_singleton()


def resolved_logo_url(brand: BrandSettings) -> str:
    return brand.logo_url or url_for("static", filename=DEFAULT_LOGO_STATIC)


def resolved_favicon_url(brand: BrandSettings) -> str:
    return brand.favicon_url or url_for("static", filename=DEFAULT_FAVICON_STATIC)


def resolved_theme_mode(brand: BrandSettings) -> str:
    """Effective mode for the current request: the user's own preference
    if the admin allows switching, otherwise whatever the admin fixed.
    """
    if not brand.supports_dark_mode:
        return "dark" if brand.dark_mode_default else "light"
    user_mode = getattr(current_user, "theme_mode", None) if current_user.is_authenticated else None
    if user_mode in ("light", "dark"):
        return user_mode
    return "dark" if brand.dark_mode_default else "light"


def theme_context() -> dict:
    brand = get_brand()
    return {
        "brand": brand,
        "app_name": brand.app_name,
        "logo_url": resolved_logo_url(brand),
        "favicon_url": resolved_favicon_url(brand),
        "theme_mode": resolved_theme_mode(brand),
        "dark_mode_toggle_enabled": brand.supports_dark_mode,
    }


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(_clamp(c) for c in rgb))


def mix(hex_a: str, hex_b: str, weight: float) -> str:
    """Blend two hex colors; weight=0 -> hex_a, weight=1 -> hex_b."""
    a, b = _hex_to_rgb(hex_a), _hex_to_rgb(hex_b)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * weight for i in range(3)))


def render_theme_css(brand: BrandSettings) -> str:
    overrides = brand.dark_overrides or {}
    dark_surface = overrides.get("surface") or mix(brand.dark, "#ffffff", 0.06)
    dark_canvas = overrides.get("canvas") or mix(brand.dark, "#000000", 0.15)
    dark_ink = overrides.get("ink") or mix(brand.light, brand.dark, 0.05)
    dark_line = overrides.get("line") or mix(brand.dark, "#ffffff", 0.14)
    dark_muted = overrides.get("muted") or mix(brand.light, brand.dark, 0.35)

    light_canvas = mix(brand.light, "#000000", 0.03)
    light_line = mix(brand.light, "#000000", 0.10)
    light_muted = mix(brand.dark, brand.light, 0.45)

    css = f"""
:root {{
  --primary: {brand.primary};
  --secondary: {brand.secondary};
  --accent: {brand.accent};
  --ink: {brand.dark};
  --muted: {light_muted};
  --line: {light_line};
  --panel: #ffffff;
  --canvas: {light_canvas};
  --shadow: 0 12px 30px rgba(0, 0, 0, .08);
}}
"""
    if brand.supports_dark_mode:
        css += f"""
[data-theme="dark"] {{
  --ink: {dark_ink};
  --muted: {dark_muted};
  --line: {dark_line};
  --panel: {dark_surface};
  --canvas: {dark_canvas};
  --shadow: 0 12px 30px rgba(0, 0, 0, .45);
}}
"""
    return css
