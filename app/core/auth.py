"""
``require_admin``: FastAPI dependency that guards every dashboard (KTR One) endpoint.

Device-facing routes (kiosk ordering and payments, KDS, token board, ``/admin/kiosk-config``,
Petpooja and PhonePe webhooks) stay open; they are not wired to this dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthNotConfigured, decode_access_token
from app.db.models.admin_user import AdminUser
from app.db.session import get_db

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False, description="Token from POST /auth/login")

# EventSource cannot send headers, so these SSE routes may take the token as ?access_token=.
_QUERY_TOKEN_PATHS = ("/admin/logs/stream",)


def revoked_key(jti: str) -> str:
    return f"admin:revoked:{jti}"


@dataclass
class AdminSession:
    user: AdminUser
    jti: str
    expires_at: datetime


def _unauthorized(detail: str = "Not signed in") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> AdminSession:
    token = credentials.credentials if credentials else None
    if not token and request.url.path in _QUERY_TOKEN_PATHS:
        token = request.query_params.get("access_token")
    if not token:
        raise _unauthorized()

    try:
        claims = decode_access_token(token)
    except AuthNotConfigured as e:
        logger.error("Dashboard auth is not configured: %s", e)
        raise HTTPException(status_code=503, detail="Sign-in is not configured on the server") from e
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("Session expired, please sign in again") from e
    except jwt.PyJWTError as e:
        raise _unauthorized("Invalid session") from e

    jti = str(claims["jti"])
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is not None:
        try:
            if await redis_client.exists(revoked_key(jti)):
                raise _unauthorized("Signed out, please sign in again")
        except HTTPException:
            raise
        except Exception:
            # Redis down: tokens stay valid until they expire rather than locking everyone out.
            logger.warning("Could not check the revoked-session list", exc_info=True)

    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError) as e:
        raise _unauthorized("Invalid session") from e
    user = (await db.execute(select(AdminUser).where(AdminUser.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _unauthorized("This account is no longer active")

    return AdminSession(
        user=user,
        jti=jti,
        expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc),
    )
