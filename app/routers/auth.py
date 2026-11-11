"""Dashboard (KTR One) sign-in: login, current session, logout. Users are created in the database."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AdminSession, require_admin, revoked_key
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    AuthNotConfigured,
    create_access_token,
    session_seconds,
    verify_password,
)
from app.db.models.admin_user import AdminUser
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Failed sign-ins allowed per username and per client address before a cool-off.
MAX_FAILED_ATTEMPTS = 5
# Higher for the address: behind a reverse proxy many people can share one.
MAX_FAILED_ATTEMPTS_PER_IP = 30
ATTEMPT_WINDOW_SECONDS = 15 * 60


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AdminUserOut(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: datetime
    user: AdminUserOut


class MeResponse(AdminUserOut):
    expires_at: datetime


def _user_out(user: AdminUser) -> AdminUserOut:
    return AdminUserOut(id=user.id, username=user.username, display_name=user.display_name, role=user.role)


def _attempt_keys(request: Request, username: str) -> list[str]:
    ip = request.client.host if request.client else "unknown"
    return [f"admin:login_fail:user:{username}", f"admin:login_fail:ip:{ip}"]


async def _too_many_attempts(redis_client, keys: list[str]) -> bool:
    if redis_client is None:
        return False
    try:
        counts = await redis_client.mget(keys)
        by_user, by_ip = (int(c or 0) for c in counts)
        return by_user >= MAX_FAILED_ATTEMPTS or by_ip >= MAX_FAILED_ATTEMPTS_PER_IP
    except Exception:
        logger.warning("Could not read the sign-in attempt counters", exc_info=True)
        return False


async def _record_failure(redis_client, keys: list[str]) -> None:
    if redis_client is None:
        return
    try:
        for key in keys:
            if await redis_client.incr(key) == 1:
                await redis_client.expire(key, ATTEMPT_WINDOW_SECONDS)
    except Exception:
        logger.warning("Could not record the failed sign-in", exc_info=True)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Exchange a username and password for a session token (valid 8 hours by default).
    Send it as ``Authorization: Bearer <token>`` on every dashboard request.
    """
    username = body.username.strip().lower()
    redis_client = getattr(request.app.state, "redis_client", None)
    keys = _attempt_keys(request, username)

    if await _too_many_attempts(redis_client, keys):
        logger.warning("Sign-in blocked after repeated failures", extra={"extra_data": {"event": "auth.login_blocked", "username": username}})
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in 15 minutes.")

    user = (await db.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none()
    # scrypt is deliberately slow: keep it off the event loop.
    password_ok = await asyncio.to_thread(
        verify_password, body.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok or not user.is_active:
        await _record_failure(redis_client, keys)
        logger.warning("Sign-in failed", extra={"extra_data": {"event": "auth.login_failed", "username": username}})
        raise HTTPException(status_code=401, detail="Wrong username or password")

    try:
        token, expires_at, _ = create_access_token(user_id=user.id, username=user.username, role=user.role)
    except AuthNotConfigured as e:
        logger.error("Dashboard auth is not configured: %s", e)
        raise HTTPException(status_code=503, detail="Sign-in is not configured on the server") from e

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    if redis_client is not None:
        try:
            await redis_client.delete(keys[0])
        except Exception:
            pass
    logger.info("Signed in", extra={"extra_data": {"event": "auth.login", "username": username}})
    return LoginResponse(
        access_token=token,
        expires_in=session_seconds(),
        expires_at=expires_at,
        user=_user_out(user),
    )


@router.get("/me", response_model=MeResponse)
async def me(session: AdminSession = Depends(require_admin)):
    """The signed-in user and when this session ends."""
    return MeResponse(**_user_out(session.user).model_dump(), expires_at=session.expires_at)


@router.post("/logout")
async def logout(request: Request, session: AdminSession = Depends(require_admin)):
    """Ends this session: the token is refused from now on."""
    redis_client = getattr(request.app.state, "redis_client", None)
    ttl = int((session.expires_at - datetime.now(timezone.utc)).total_seconds())
    if redis_client is not None and ttl > 0:
        try:
            await redis_client.set(revoked_key(session.jti), "1", ex=ttl)
        except Exception:
            logger.warning("Could not revoke the session in Redis", exc_info=True)
    logger.info("Signed out", extra={"extra_data": {"event": "auth.logout", "username": session.user.username}})
    return {"status": "signed_out"}
