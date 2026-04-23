"""HTTP + SSE routes for Token Display System (TMS)."""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis_client
from app.db.session import SessionLocal
from app.kds.notify import KDS_NOTIFY_CHANNEL
from app.tms.schemas import TmsHealthResponse
from app.tms.service import TmsTokenService

logger = logging.getLogger(__name__)

router = APIRouter()


def _tms_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis_client),
) -> TmsTokenService:
    return TmsTokenService(db, redis)


@router.get("/health", response_model=TmsHealthResponse)
async def tms_health(service: TmsTokenService = Depends(_tms_service)):
    return TmsHealthResponse(live_window_minutes=service.live_window_minutes)


@router.get("/snapshot")
async def tms_snapshot(service: TmsTokenService = Depends(_tms_service)):
    """SSR-friendly JSON; pair with ``GET /tms/stream`` for live updates."""
    return await service.get_snapshot()


@router.get("/stream")
async def tms_sse(request: Request):
    """
    Server-Sent Events: first event is a full snapshot; then forwards kitchen pub/sub.

    TMS clients should use ``payload.speech`` on ``TMS_ANNOUNCE`` with ``SpeechSynthesisUtterance``.
    """
    redis = request.app.state.redis_client

    async def event_gen():
        async with SessionLocal() as db:
            svc = TmsTokenService(db, redis)
            snap = await svc.get_snapshot()
        yield f"data: {json.dumps({'type': 'SNAPSHOT', 'payload': snap})}\n\n"

        if redis is None:
            while True:
                await asyncio.sleep(25)
                yield ": ping\n\n"

        pubsub = redis.pubsub()
        await pubsub.subscribe(KDS_NOTIFY_CHANNEL)
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=25.0)
                if msg is None:
                    yield ": ping\n\n"
                    continue
                if msg.get("type") == "message" and msg.get("data"):
                    yield f"data: {msg['data']}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(KDS_NOTIFY_CHANNEL)
                await pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
