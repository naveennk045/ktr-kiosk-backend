from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

import redis.asyncio as redis
from app.core.dependencies import get_db, get_redis_client
from app.db.models.edc_config import EdcConfig
from app.db.models.item_availability import ItemAvailability
from app.db.models.order import Order
from app.db.models.cash_pin import CashPin
from app.db.schemas.admin import ItemAvailabilityUpdate, ItemAvailabilityResponse
from typing import List
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["admin"])

class EdcConfigResponse(BaseModel):
    id: int
    merchant_id: str
    store_id: str
    terminal_id: str
    mid_on_device: str | None
    store_name: str | None

    class Config:
        from_attributes = True

class TransactionResponse(BaseModel):
    order_id: str
    amount: float
    payment_status: str | None
    payment_method: str | None
    created_at: datetime
    provider_resp: dict | None
    provider_code: str | None
    cash_collected_by_staff_name: str | None = None

    class Config:
        from_attributes = True

@router.get("/edc-config", response_model=List[EdcConfigResponse])
async def get_edc_configs(db: AsyncSession = Depends(get_db)):
    stmt = select(EdcConfig)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/transactions", response_model=List[TransactionResponse])
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Order).order_by(desc(Order.created_at)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    orders = result.scalars().all()

    # Map Order to TransactionResponse
    # Assuming Order model has created_at, amount (in paise usually or float?)
    # Let's check Order model. Assuming standard fields.

    return [
        TransactionResponse(
            order_id=o.order_id,
            amount=o.total_amount_include_tax,
            payment_status=o.payment_status,
            payment_method=o.payment_method,
            created_at=o.created_at,
            provider_resp=o.provider_resp,
            provider_code=o.provider_code,
            cash_collected_by_staff_name=o.cash_collected_by_staff_name,
        )
        for o in orders
    ]


class CashPinStaff(BaseModel):
    """Staff entries (PIN values are not returned; manage PINs via DB or a secure tool)."""
    id: int
    staff_name: str

    class Config:
        from_attributes = True


@router.get("/cash-pins", response_model=List[CashPinStaff])
async def list_cash_pins(db: AsyncSession = Depends(get_db)):
    """List registered cash-collection staff (id + name)."""
    stmt = select(CashPin).order_by(CashPin.id)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/catalog/availability", response_model=List[ItemAvailabilityResponse])
async def get_item_availabilities(db: AsyncSession = Depends(get_db)):
    """Fetch all manual item availability overrides."""
    stmt = select(ItemAvailability)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/catalog/availability", response_model=ItemAvailabilityResponse)
async def update_item_availability(
    req: ItemAvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client)
):
    """Update or create an availability override for an item SKU."""
    stmt = select(ItemAvailability).where(ItemAvailability.sku_code == req.sku_code)
    result = await db.execute(stmt)
    availability = result.scalar_one_or_none()

    if availability:
        availability.is_available = req.is_available
    else:
        availability = ItemAvailability(
            sku_code=req.sku_code,
            is_available=req.is_available
        )
        db.add(availability)

    await db.commit()
    await db.refresh(availability)

    # Invalidate catalog cache globally so frontend gets fresh status
    # Simple strategy: clear all catalog keys
    keys = await redis_client.keys("petpooja_catalog_data_*")
    if keys:
        await redis_client.delete(*keys)

    return availability
