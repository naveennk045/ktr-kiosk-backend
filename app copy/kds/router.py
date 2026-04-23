"""HTTP + WebSocket routes for Kitchen Display System (KDS)."""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis_client
from app.db.session import SessionLocal
from app.db.models.order import KitchenLineStatus
from app.kds.notify import KDS_NOTIFY_CHANNEL
from app.kds.schemas import KdsHealthResponse, KdsLineStatusPatch
from app.kds.service import DEFAULT_BOARD_ROWS, KdsBoardService

logger = logging.getLogger(__name__)

router = APIRouter()


def _kds_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis_client),
    max_rows: int = Query(DEFAULT_BOARD_ROWS, ge=1, le=100, description="Max KOT cards per screen"),
) -> KdsBoardService:
    return KdsBoardService(db, redis, max_rows=max_rows)


@router.get("/health", response_model=KdsHealthResponse)
async def kds_health(service: KdsBoardService = Depends(_kds_service)):
    """KDS health + Option B window metadata."""
    return KdsHealthResponse(live_window_minutes=service.live_window_minutes)


@router.get("/board")
async def kds_live_board(service: KdsBoardService = Depends(_kds_service)):
    """
    Live board: paid orders (Option B), line-level kitchen status, clubbed totals.

    Use ``max_rows`` to cap how many KOT cards the UI requests at once.
    """
    return await service.get_board_snapshot()


@router.patch("/items/{line_id}/status")
async def kds_patch_line_status(
    line_id: int,
    body: KdsLineStatusPatch,
    service: KdsBoardService = Depends(_kds_service),
):
    """Chef advances one line: GETTING_READY → READY_FOR_PICKUP → PICKED_UP."""
    return await service.set_line_kitchen_status(line_id, body.status)


@router.websocket("/ws")
async def kds_websocket(
    websocket: WebSocket,
    max_rows: int = Query(DEFAULT_BOARD_ROWS, ge=1, le=100),
):
    """
    Initial board snapshot, then Redis ``kds:notify`` messages (JSON text).

    If Redis is unavailable at app startup, connect still works with snapshot-only.
    """
    await websocket.accept()
    redis = websocket.app.state.redis_client
    try:
        async with SessionLocal() as db:
            service = KdsBoardService(db, redis, max_rows=max_rows)
            snap = await service.get_board_snapshot()
        await websocket.send_json({"type": "SNAPSHOT", "payload": snap})
    except Exception as e:
        logger.exception("KDS WS snapshot failed: %s", e)
        await websocket.close(code=1011)
        return

    if redis is None:
        try:
            while True:
                await asyncio.sleep(30)
                await websocket.send_json({"type": "PING", "payload": {}})
        except WebSocketDisconnect:
            return

    pubsub = redis.pubsub()
    await pubsub.subscribe(KDS_NOTIFY_CHANNEL)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
            if msg and msg.get("type") == "message" and msg.get("data"):
                await websocket.send_text(msg["data"])
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await pubsub.unsubscribe(KDS_NOTIFY_CHANNEL)
            await pubsub.close()
        except Exception:
            pass
