"""HTTP + WebSocket routes for Kitchen Display System (KDS)."""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_db,
    get_redis_client,
    get_store_context,
    resolve_active_store,
)
from app.db.models.store import Store
from app.db.session import SessionLocal
from app.kds.notify import KDS_NOTIFY_CHANNEL
from app.kds.schemas import KdsHealthResponse, KdsLineStatusPatch
from app.kds.service import DEFAULT_BOARD_ROWS, KdsBoardService

logger = logging.getLogger(__name__)

router = APIRouter()


async def _ws_send_json(websocket: WebSocket, payload: dict) -> bool:
    """Return False if the client is gone (do not log as application error)."""
    try:
        await websocket.send_json(payload)
        return True
    except WebSocketDisconnect:
        return False
    except Exception as e:
        logger.debug("KDS WebSocket send_json closed: %s", e)
        return False


async def _ws_send_text(websocket: WebSocket, text: str) -> bool:
    try:
        await websocket.send_text(text)
        return True
    except WebSocketDisconnect:
        return False
    except Exception as e:
        logger.debug("KDS WebSocket send_text closed: %s", e)
        return False


def _kds_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis_client),
    store: Store = Depends(get_store_context),
    max_rows: int = Query(DEFAULT_BOARD_ROWS, ge=1, le=100, description="Max KOT cards per screen"),
) -> KdsBoardService:
    return KdsBoardService(db, redis, store_id=store.id, max_rows=max_rows)


@router.get("/health", response_model=KdsHealthResponse)
async def kds_health(service: KdsBoardService = Depends(_kds_service)):
    """KDS health + Option B window metadata (requires ``X-Store-Id``)."""
    return KdsHealthResponse(live_window_minutes=service.live_window_minutes)


@router.get("/board")
async def kds_live_board(service: KdsBoardService = Depends(_kds_service)):
    """
    Live board for the store: paid orders (Option B), line-level ``order_status``, clubbed totals.

    Use ``max_rows`` to cap how many KOT cards the UI requests at once.
    """
    return await service.get_board_snapshot()


@router.patch("/items/{line_id}/status")
async def kds_patch_line_status(
    line_id: int,
    body: KdsLineStatusPatch,
    service: KdsBoardService = Depends(_kds_service),
):
    """Chef advances one line: NOT_ACCEPTED → PREPARING → READY → COLLECTED."""
    return await service.set_line_item_status(line_id, body.status, body.quantity)


@router.websocket("/ws")
async def kds_websocket(
    websocket: WebSocket,
    max_rows: int = Query(DEFAULT_BOARD_ROWS, ge=1, le=100),
):
    """
    Initial board snapshot, then Redis ``kds:notify`` messages (JSON text).

    Send ``X-Store-Id`` as a WebSocket subprotocol header (lowercased to ``x-store-id``) or
    ``?store_id=`` as a numeric fallback.
    """
    await websocket.accept()
    redis = websocket.app.state.redis_client
    raw = (websocket.headers.get("x-store-id") or "").strip()
    if not raw:
        q = websocket.query_params.get("store_id")
        if q and q.strip().isdigit():
            raw = q.strip()
    if not raw:
        await websocket.close(code=4400)
        return

    store_id_ws: int
    try:
        async with SessionLocal() as db:
            store = await resolve_active_store(db, raw)
            store_id_ws = store.id
            service = KdsBoardService(db, redis, store_id=store.id, max_rows=max_rows)
            snap = await service.get_board_snapshot()
        if not await _ws_send_json(websocket, {"type": "SNAPSHOT", "payload": snap}):
            return
    except Exception as e:
        logger.exception("KDS WS snapshot failed: %s", e)
        await websocket.close(code=1011)
        return

    if redis is None:
        try:
            while True:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    logger.debug("KDS WS ping loop cancelled (shutdown)")
                    return
                if not await _ws_send_json(websocket, {"type": "PING", "payload": {}}):
                    return
        except WebSocketDisconnect:
            return

    pubsub = redis.pubsub()
    await pubsub.subscribe(KDS_NOTIFY_CHANNEL)
    try:
        while True:
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
            except asyncio.CancelledError:
                logger.debug("KDS WS pubsub cancelled (shutdown / reload)")
                break
            if msg and msg.get("type") == "message" and msg.get("data"):
                raw_data = msg["data"]
                try:
                    body = json.loads(raw_data)
                    p = body.get("payload") or {}
                    psid = p.get("store_id")
                    if psid is not None and int(psid) != store_id_ws:
                        continue
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
                if not await _ws_send_text(websocket, raw_data):
                    break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await pubsub.unsubscribe(KDS_NOTIFY_CHANNEL)
            await pubsub.close()
        except Exception:
            pass
