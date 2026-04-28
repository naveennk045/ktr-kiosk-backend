from collections import defaultdict
from typing import List

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis_client, get_store_context
from app.db.models.cash_pin import CashPin
from app.db.models.store import KioskTerminal, Store, StorePinelabsCredentials
from app.services.store_cache import invalidate_store_cache

router = APIRouter(prefix="/admin", tags=["admin"])


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
