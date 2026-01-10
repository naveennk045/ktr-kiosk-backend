from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.dependencies import get_db
from app.db.models.edc_config import EdcConfig
from app.db.models.order import Order
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
    tid_on_device: str | None

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
            provider_code=o.provider_code
        ) for o in orders
    ]
