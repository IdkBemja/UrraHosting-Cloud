"""Pure unit tests for the theming engine (plan.md section 7): the
"UrraHosting Theme" default palette, and that turning off
`supports_dark_mode` actually removes the `[data-theme="dark"]` block
instead of just hiding the toggle client-side (an admin who disables
dark mode should get a stylesheet that has no dark rules at all).
"""

from __future__ import annotations

from app.models.brand_settings import (
    DEFAULT_ACCENT,
    DEFAULT_DARK,
    DEFAULT_LIGHT,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
    BrandSettings,
)
from app.services.theming import mix, render_theme_css


def _brand(**overrides) -> BrandSettings:
    defaults = dict(
        app_name="UrraHosting Cloud",
        primary=DEFAULT_PRIMARY,
        secondary=DEFAULT_SECONDARY,
        accent=DEFAULT_ACCENT,
        dark=DEFAULT_DARK,
        light=DEFAULT_LIGHT,
        supports_dark_mode=True,
        dark_mode_default=False,
        dark_overrides=None,
    )
    defaults.update(overrides)
    return BrandSettings(**defaults)


def test_default_preset_uses_dashboard_palette():
    brand = _brand()
    css = render_theme_css(brand)

    assert "#e25822" in css  # --primary (docker-host main.css)
    assert "#ff4500" in css  # --secondary
    assert "#ff4081" in css  # --accent


def test_dark_mode_block_present_when_supported():
    brand = _brand(supports_dark_mode=True)
    css = render_theme_css(brand)

    assert '[data-theme="dark"]' in css


def test_dark_mode_block_absent_when_admin_disables_it():
    brand = _brand(supports_dark_mode=False)
    css = render_theme_css(brand)

    assert '[data-theme="dark"]' not in css


def test_mix_interpolates_between_two_colors():
    assert mix("#000000", "#ffffff", 0.0) == "#000000"
    assert mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert mix("#000000", "#ffffff", 0.5) == "#808080"
