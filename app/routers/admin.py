from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.dependencies import get_db
from app.db.models.edc_config import EdcConfig
from app.db.models.cash_pin import CashPin
from typing import List
from pydantic import BaseModel

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

@router.get("/edc-config", response_model=List[EdcConfigResponse])
async def get_edc_configs(db: AsyncSession = Depends(get_db)):
    stmt = select(EdcConfig)
    result = await db.execute(stmt)
    return result.scalars().all()


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
