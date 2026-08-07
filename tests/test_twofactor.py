from __future__ import annotations

import pyotp
import pytest

from app.extensions import db
from app.models.user import User
from app.services import twofactor


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


def test_verify_code_accepts_current_totp_and_rejects_wrong_code():
    secret = twofactor.generate_secret()
    current_code = pyotp.TOTP(secret).now()

    assert twofactor.verify_code(secret, current_code) is True
    assert twofactor.verify_code(secret, "000000") is False


def test_verify_code_rejects_non_numeric_input():
    secret = twofactor.generate_secret()
    assert twofactor.verify_code(secret, "not-a-code") is False
    assert twofactor.verify_code(secret, "") is False


def test_recovery_codes_are_one_time_use(app, user):
    plaintext_codes = twofactor.generate_recovery_codes()
    user.totp_recovery_codes_json = twofactor.hash_recovery_codes(plaintext_codes)
    db.session.commit()

    first_code = plaintext_codes[0]
    assert twofactor.consume_recovery_code(user, first_code) is True
    db.session.commit()

    # Same code again must fail - it was removed from the stored list.
    assert twofactor.consume_recovery_code(user, first_code) is False
    assert len(user.totp_recovery_codes_json) == len(plaintext_codes) - 1


def test_consume_recovery_code_rejects_unknown_code(app, user):
    user.totp_recovery_codes_json = twofactor.hash_recovery_codes(twofactor.generate_recovery_codes())
    db.session.commit()

    assert twofactor.consume_recovery_code(user, "not-a-real-code") is False
