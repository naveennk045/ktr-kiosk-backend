"""HTTP + SSE routes for Token Display System (TMS)."""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_db,
    get_redis_client,
    get_store_context,
    get_store_context_flexible,
)
from app.db.models.store import Store
from app.db.session import SessionLocal
from app.kds.notify import KDS_NOTIFY_CHANNEL
from app.tms.schemas import TmsHealthResponse
from app.tms.service import TmsTokenService

logger = logging.getLogger(__name__)

router = APIRouter()


def _tms_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis_client),
    store: Store = Depends(get_store_context),
) -> TmsTokenService:
    return TmsTokenService(db, redis, store_id=store.id)


@router.get("/health", response_model=TmsHealthResponse)
async def tms_health(service: TmsTokenService = Depends(_tms_service)):
    return TmsHealthResponse(live_window_minutes=service.live_window_minutes)


@router.get("/snapshot")
async def tms_snapshot(service: TmsTokenService = Depends(_tms_service)):
    """SSR-friendly JSON; pair with ``GET /tms/stream`` for live updates."""
    return await service.get_snapshot()


@router.get("/stream")
async def tms_sse(
    request: Request,
    store: Store = Depends(get_store_context_flexible),
):
    """
    Server-Sent Events: first event is a full snapshot; then forwards kitchen pub/sub.

    Use ``X-Store-Id`` or ``?store_id=`` (browser EventSource cannot set headers).

    TMS clients should use ``payload.speech`` on ``TMS_ANNOUNCE`` with ``SpeechSynthesisUtterance``.
    """
    redis = request.app.state.redis_client
    store_id = store.id

    async def event_gen():
        """
        Long-lived SSE body. Swallows ``CancelledError`` at yield/redis boundaries so
        uvicorn/shutdown does not treat normal teardown as an unhandled ASGI error.
        """
        pubsub = None
        try:
            async with SessionLocal() as db:
                svc = TmsTokenService(db, redis, store_id=store_id)
                snap = await svc.get_snapshot()
            line = f"data: {json.dumps({'type': 'SNAPSHOT', 'payload': snap})}\n\n"
            try:
                yield line
            except asyncio.CancelledError:
                logger.debug("TMS SSE cancelled while sending snapshot (shutdown)")
                return
        except asyncio.CancelledError:
            logger.debug("TMS SSE cancelled before first chunk")
            return

        if redis is None:
            while True:
                try:
                    await asyncio.sleep(25)
                except asyncio.CancelledError:
                    logger.debug("TMS SSE ping sleep cancelled")
                    return
                try:
                    yield ": ping\n\n"
                except asyncio.CancelledError:
                    return

        reconnect_delay = 1.0
        while True:
            pubsub = None
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe(KDS_NOTIFY_CHANNEL)
                logger.info("TMS SSE subscribed to channel '%s' for store_id=%s", KDS_NOTIFY_CHANNEL, store_id)
                reconnect_delay = 1.0

                while True:
                    try:
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=25.0)
                    except asyncio.CancelledError:
                        logger.debug("TMS SSE pubsub cancelled (shutdown / reload)")
                        return
                    except RedisConnectionError as conn_err:
                        logger.warning(
                            "TMS SSE Redis pubsub disconnected for store_id=%s: %s. Reconnecting...",
                            store_id,
                            conn_err,
                        )
                        break

                    if msg is None:
                        try:
                            yield ": ping\n\n"
                        except asyncio.CancelledError:
                            return
                        continue
                    if msg.get("type") == "message" and msg.get("data"):
                        raw_data = msg["data"]
                        try:
                            body = json.loads(raw_data)
                            p = body.get("payload") or {}
                            psid = p.get("store_id")
                            if psid is not None and int(psid) != store_id:
                                continue
                        except (ValueError, TypeError):
                            pass
                        try:
                            yield f"data: {raw_data}\n\n"
                        except asyncio.CancelledError:
                            return
            finally:
                try:
                    if pubsub is not None:
                        await pubsub.unsubscribe(KDS_NOTIFY_CHANNEL)
                        await pubsub.close()
                except Exception:
                    pass

            try:
                await asyncio.sleep(reconnect_delay)
            except asyncio.CancelledError:
                return
            reconnect_delay = min(reconnect_delay * 2, 10.0)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
