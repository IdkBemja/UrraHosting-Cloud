"""TOTP-based 2FA (Fase 3, plan.md section 8): setup/verify/recovery
codes. Recovery codes are stored bcrypt-hashed (never plaintext) and are
one-time-use - `consume_recovery_code` removes a matched code from the
stored list so it can't be replayed.
"""

from __future__ import annotations

import base64
import io
import secrets

import pyotp
import qrcode

from ..extensions import bcrypt, db
from ..models.user import User

_RECOVERY_CODE_COUNT = 8


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(user: User, secret: str, issuer_name: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer_name)


def qr_code_data_uri(uri: str) -> str:
    """Renders the provisioning URI as a PNG data: URI so the setup page
    can embed it directly (<img src="...">) without a separate route or
    persisting the QR image anywhere.
    """
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_code(secret: str, code: str) -> bool:
    if not code or not code.strip().isdigit():
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def generate_recovery_codes() -> list[str]:
    return [secrets.token_hex(5) for _ in range(_RECOVERY_CODE_COUNT)]


def hash_recovery_codes(plaintext_codes: list[str]) -> list[str]:
    return [bcrypt.generate_password_hash(code).decode("utf-8") for code in plaintext_codes]


def consume_recovery_code(user: User, code: str) -> bool:
    """Returns True and removes the matching hash from `user`'s list if
    `code` matches one of the stored recovery codes. Caller must
    db.session.commit().
    """
    if not user.totp_recovery_codes_json or not code:
        return False
    remaining = list(user.totp_recovery_codes_json)
    for stored_hash in remaining:
        if bcrypt.check_password_hash(stored_hash, code.strip()):
            remaining.remove(stored_hash)
            user.totp_recovery_codes_json = remaining
            db.session.add(user)
            return True
    return False
