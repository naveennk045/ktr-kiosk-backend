"""
Dashboard authentication primitives: password hashing (scrypt, standard library only) and
signed session tokens (JWT, HS256).

Sessions last ``ADMIN_SESSION_HOURS`` (8 by default) and are not refreshed: after that the
user signs in again. Logout revokes the token's ``jti`` in Redis until it would have expired.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt

from app.core.config import settings

JWT_ALGORITHM = "HS256"
TOKEN_AUDIENCE = "ktr-one"
MIN_SECRET_LENGTH = 32

# scrypt cost parameters (≈64 MB, well under 100 ms per check on a server).
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 128 * 1024 * 1024
_KEY_LEN = 32
_SCHEME = "scrypt"


class AuthNotConfigured(RuntimeError):
    """ADMIN_JWT_SECRET is missing or too short."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    """``scrypt$N$r$p$salt$hash`` — the value stored in ``admin_users.password_hash``."""
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM, dklen=_KEY_LEN,
    )
    return f"{_SCHEME}${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Unknown or malformed hashes never match."""
    try:
        scheme, n, r, p, salt, expected = (stored or "").split("$")
        if scheme != _SCHEME:
            return False
        want = _unb64(expected)
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
            maxmem=_SCRYPT_MAXMEM, dklen=len(want),
        )
        return hmac.compare_digest(got, want)
    except (ValueError, TypeError):
        return False


# Checked when the username does not exist, so a wrong username costs the same as a wrong password.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def _secret() -> str:
    secret = (settings.ADMIN_JWT_SECRET or "").strip()
    if len(secret) < MIN_SECRET_LENGTH:
        raise AuthNotConfigured(
            f"ADMIN_JWT_SECRET must be set to at least {MIN_SECRET_LENGTH} random characters"
        )
    return secret


def session_seconds() -> int:
    return int(settings.ADMIN_SESSION_HOURS * 3600)


def create_access_token(*, user_id: int, username: str, role: str) -> tuple[str, datetime, str]:
    """Returns (token, expires_at, jti)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=session_seconds())
    jti = uuid4().hex
    payload = {
        "sub": str(user_id),
        "usr": username,
        "role": role,
        "aud": TOKEN_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM), expires_at, jti


def decode_access_token(token: str) -> dict[str, Any]:
    """Verifies signature, expiry and audience. Raises ``jwt.PyJWTError`` when invalid."""
    return jwt.decode(
        token,
        _secret(),
        algorithms=[JWT_ALGORITHM],
        audience=TOKEN_AUDIENCE,
        options={"require": ["exp", "iat", "sub", "jti"]},
    )
