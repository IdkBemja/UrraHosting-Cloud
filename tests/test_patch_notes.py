"""Tests for the "Novedades" feature: parsing CHANGELOG.md's most recent
entry (app/services/patch_notes.py) and persisting per-user dismissal on
User.dismissed_patch_notes_version (the field app/main.py's inject_globals()
compares against to decide show_patch_notes).

The full app.main:create_app() needs Postgres (see conftest.py's `app`
fixture docstring), so route-level coverage of drive/settings.py's
dismiss_patch_notes lives out of reach here the same way the rest of this
suite handles it - these tests cover the parsing logic and the model field
directly, mirroring test_twofactor.py's style.
"""

from __future__ import annotations

import re

import pytest

from app.extensions import db
from app.models.user import User
from app.services import patch_notes

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.fixture
def user(app):
    u = User(
        email="a@example.com",
        username="a",
        password_hash="x",
        role="member",
        quota_bytes=1000,
    )
    db.session.add(u)
    db.session.commit()
    return u


def test_parse_latest_entry_takes_the_first_version_block():
    text = (
        "# Changelog\n\n"
        "## [2.1.0] - 2026-01-01\n\n"
        "### Added\n"
        "- Cosa nueva.\n\n"
        "## [2.0.0] - 2025-01-01\n\n"
        "- Cosa vieja, no debe aparecer.\n"
    )
    notes = patch_notes._parse_latest_entry(text)
    assert notes.version == "2.1.0"
    assert "Cosa nueva" in notes.html
    assert "Cosa vieja" not in notes.html


def test_parse_latest_entry_strips_the_date_from_the_header_line():
    text = "## [1.0.0] - 2026-01-01\n\nHola.\n"
    notes = patch_notes._parse_latest_entry(text)
    assert "2026-01-01" not in notes.html
    assert "<li>" not in notes.html


def test_parse_latest_entry_sanitizes_raw_html():
    text = "## [1.0.0]\n\n<script>alert(1)</script>\n\nTexto normal.\n"
    notes = patch_notes._parse_latest_entry(text)
    assert "<script" not in notes.html
    assert "Texto normal" in notes.html


def test_parse_latest_entry_requires_at_least_one_version_header():
    with pytest.raises(ValueError):
        patch_notes._parse_latest_entry("# Changelog\n\nNada aqui.\n")


def test_get_patch_notes_reads_the_real_changelog():
    notes = patch_notes.get_patch_notes()
    assert _VERSION_RE.match(notes.version)
    assert notes.html
    assert "##" not in notes.html


def test_fresh_user_has_not_dismissed_any_version(user):
    assert user.dismissed_patch_notes_version is None
    assert user.dismissed_patch_notes_version != patch_notes.current_version()


def test_dismissing_persists_the_current_version(app, user):
    user.dismissed_patch_notes_version = patch_notes.current_version()
    db.session.commit()

    reloaded = db.session.get(User, user.id)
    assert reloaded.dismissed_patch_notes_version == patch_notes.current_version()
