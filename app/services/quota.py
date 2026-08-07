from __future__ import annotations

from .storage.base import StorageError
from ..extensions import db
from ..models.user import User


def check_user_quota(user: User, additional_bytes: int) -> None:
    if user.storage_used_bytes + additional_bytes > user.quota_bytes:
        raise StorageError("Cuota de almacenamiento del usuario excedida")


def apply_usage_delta(user: User, delta_bytes: int) -> None:
    user.storage_used_bytes = max(user.storage_used_bytes + delta_bytes, 0)
    db.session.add(user)
