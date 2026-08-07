from __future__ import annotations

import pytest

from app.extensions import db
from app.models.user import User
from app.services.quota import apply_usage_delta, check_user_quota
from app.services.storage.base import StorageError


@pytest.fixture
def user(app):
    u = User(
        email="a@example.com",
        username="a",
        password_hash="x",
        role="member",
        quota_bytes=1000,
        storage_used_bytes=0,
    )
    db.session.add(u)
    db.session.commit()
    return u


def test_check_user_quota_allows_within_limit(app, user):
    check_user_quota(user, 500)  # must not raise


def test_check_user_quota_rejects_over_limit(app, user):
    user.storage_used_bytes = 900
    with pytest.raises(StorageError):
        check_user_quota(user, 200)


def test_apply_usage_delta_increments_and_decrements(app, user):
    apply_usage_delta(user, 300)
    assert user.storage_used_bytes == 300

    apply_usage_delta(user, -100)
    assert user.storage_used_bytes == 200


def test_apply_usage_delta_never_goes_negative(app, user):
    apply_usage_delta(user, 50)
    apply_usage_delta(user, -500)
    assert user.storage_used_bytes == 0
