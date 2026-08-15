from __future__ import annotations

from .storage.base import StorageError
from ..extensions import db
from ..models.user import User


def check_user_quota(user: User, additional_bytes: int) -> None:
    limit = user.quota_bytes
    if limit == 0:
        # 0 = unlimited per-user quota (see User.storage_available_bytes) -
        # still bounded by the instance's own total capacity.
        from ..models.instance_settings import InstanceSettings

        limit = InstanceSettings.get_singleton().total_quota_bytes
    if user.storage_used_bytes + additional_bytes > limit:
        raise StorageError("Cuota de almacenamiento del usuario excedida")


def apply_usage_delta(user: User, delta_bytes: int) -> None:
    user.storage_used_bytes = max(user.storage_used_bytes + delta_bytes, 0)
    db.session.add(user)
