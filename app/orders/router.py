from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.db.models import Order, OrderItem


router = APIRouter(prefix="/orders", tags=["orders"])


class OrderItemIn(BaseModel):
    menu_legacy_id: int
    name: str
    unit_price: float
    quantity: int = 1
    options: dict | None = None


class OrderIn(BaseModel):
    notes: str | None = None
    items: List[OrderItemIn]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderIn, db: AsyncSession = Depends(get_db)):
    order = Order(notes=payload.notes)
    db.add(order)
    await db.flush()

    total = 0.0
    for item in payload.items:
        line_total = float(item.unit_price) * item.quantity
        total += line_total
        db.add(
            OrderItem(
                order_id=order.id,
                menu_legacy_id=item.menu_legacy_id,
                name=item.name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                options=item.options,
            )
        )

    order.total_amount = total
    await db.commit()
    await db.refresh(order)
    return {"id": order.id, "status": order.status, "total_amount": float(order.total_amount)}


@router.get("/")
async def list_orders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).order_by(Order.id.desc()))
    orders = result.scalars().all()
    return [
        {"id": o.id, "status": o.status, "notes": o.notes, "total_amount": float(o.total_amount)}
        for o in orders
    ]


