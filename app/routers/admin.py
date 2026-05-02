from collections import defaultdict
from collections import deque
import asyncio
import json
import os
from pathlib import Path
import re
from typing import List

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis_client, get_store_context
from app.db.models.cash_pin import CashPin
from app.db.models.store import KioskTerminal, Store, StorePinelabsCredentials
from app.services.store_cache import invalidate_store_cache

router = APIRouter(prefix="/admin", tags=["admin"])
LOG_FILE_PATH = Path("app.log")
LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>[^-]+?)\s+-\s+\[(?P<level>[A-Z]+)\]\s+-\s+(?P<logger>[^-]+?)\s+-\s+(?P<message>.*)$"
)


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    """Return last N lines from a UTF-8 text file."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=max_lines)]


def _parse_log_line(line: str) -> dict:
    """
    Parse standard app log format into frontend-friendly fields.
    Falls back to `raw` only if format does not match.
    """
    match = LOG_LINE_PATTERN.match(line)
    if not match:
        return {
            "timestamp": None,
            "level": "UNKNOWN",
            "logger": None,
            "message": line,
            "raw": line,
        }
    data = match.groupdict()
    return {
        "timestamp": data["timestamp"].strip(),
        "level": data["level"].strip(),
        "logger": data["logger"].strip(),
        "message": data["message"],
        "raw": line,
    }


class KioskTerminalItem(BaseModel):
    id: int
    terminal_id: str
    pinelabs_store_id: str
    mid_on_device: str | None = None
    label: str | None = None
    is_active: bool

    class Config:
        from_attributes = True


class KioskConfigResponse(BaseModel):
    store_id: int = Field(description="Internal numeric store id")
    store_code: str
    store_name: str
    pinelabs_configured: bool = Field(
        description="Whether shared PineLabs API credentials exist for this store"
    )
    terminals: List[KioskTerminalItem]


@router.get("/kiosk-config", response_model=List[KioskConfigResponse])
async def get_kiosk_config(db: AsyncSession = Depends(get_db)):
    """
    **All active stores** — metadata and PineLabs `kiosk_terminals` per outlet.

    No `X-Store-Id` or query params: clients use this to discover `store_id`, store codes,
    and terminal ids for configuration.
    """
    stmt = select(Store).where(Store.is_active.is_(True)).order_by(Store.id)
    stores = (await db.execute(stmt)).scalars().all()
    if not stores:
        return []

    store_ids = [s.id for s in stores]

    pinelabs_store_ids = set(
        (
            await db.execute(
                select(StorePinelabsCredentials.store_id).where(
                    StorePinelabsCredentials.store_id.in_(store_ids)
                )
            )
        ).scalars().all()
    )

    t_stmt = (
        select(KioskTerminal)
        .where(KioskTerminal.store_id.in_(store_ids))
        .order_by(KioskTerminal.store_id, KioskTerminal.id)
    )
    terminals_all = (await db.execute(t_stmt)).scalars().all()
    terminals_by_store: defaultdict[int, list] = defaultdict(list)
    for t in terminals_all:
        terminals_by_store[t.store_id].append(t)

    return [
        KioskConfigResponse(
            store_id=s.id,
            store_code=s.store_code,
            store_name=s.store_name,
            pinelabs_configured=s.id in pinelabs_store_ids,
            terminals=[
                KioskTerminalItem.model_validate(term)
                for term in terminals_by_store[s.id]
            ],
        )
        for s in stores
    ]


class CashPinStaff(BaseModel):
    """Staff entries (PIN values are not returned; manage PINs via DB or a secure tool)."""
    id: int
    staff_name: str

    class Config:
        from_attributes = True


@router.get("/cash-pins", response_model=List[CashPinStaff])
async def list_cash_pins(
    db: AsyncSession = Depends(get_db),
    store: Store = Depends(get_store_context),
):
    """List registered cash-collection staff (id + name) for this store."""
    stmt = (
        select(CashPin)
        .where(CashPin.store_id == store.id)
        .order_by(CashPin.id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/cache/invalidate")
async def invalidate_store_caches(
    store: Store = Depends(get_store_context),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """Bust Redis cache for this store (credentials + meta)."""
    await invalidate_store_cache(redis_client, store.id)
    return {"status": "ok", "store_id": store.id}


@router.get("/logs")
async def get_app_logs(
    lines: int = Query(200, ge=1, le=2000),
    contains: str | None = Query(None, description="Optional case-insensitive line filter"),
):
    """
    Return recent lines from `app.log` for frontend diagnostics.
    """
    if not LOG_FILE_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    rows = await asyncio.to_thread(_tail_lines, LOG_FILE_PATH, lines)
    if contains:
        needle = contains.lower()
        rows = [line for line in rows if needle in line.lower()]

    return {
        "path": str(LOG_FILE_PATH.resolve()),
        "count": len(rows),
        "entries": [_parse_log_line(line) for line in rows],
    }


@router.get("/logs/stream")
async def stream_app_logs(
    request: Request,
    contains: str | None = Query(None, description="Optional case-insensitive line filter"),
    initial_lines: int = Query(50, ge=0, le=500),
):
    """
    SSE stream of `app.log` so frontend can watch logs in real-time.
    """
    if not LOG_FILE_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    async def event_gen():
        needle = contains.lower() if contains else None
        if initial_lines > 0:
            for line in await asyncio.to_thread(_tail_lines, LOG_FILE_PATH, initial_lines):
                if needle and needle not in line.lower():
                    continue
                yield f"data: {json.dumps({'type': 'log', 'entry': _parse_log_line(line)})}\n\n"

        with LOG_FILE_PATH.open("r", encoding="utf-8", errors="replace") as fp:
            fp.seek(0, os.SEEK_END)
            while True:
                if await request.is_disconnected():
                    break

                line = await asyncio.to_thread(fp.readline)
                if not line:
                    yield ": ping\n\n"
                    await asyncio.sleep(1.0)
                    continue

                value = line.rstrip("\n")
                if needle and needle not in value.lower():
                    continue
                yield f"data: {json.dumps({'type': 'log', 'entry': _parse_log_line(value)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
