"""KDS — live board, clubbed totals, chef line status updates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import (
    KitchenLineStatus,
    Order,
    OrderItem,
    PaymentStatus,
)
from app.kds.constants import LIVE_ORDERS_WINDOW_MINUTES
from app.kds.notify import emit_kitchen_event, line_ready_speech

DEFAULT_BOARD_ROWS = 20
MAX_BOARD_ROWS_CAP = 100

_STATUS_RANK: dict[KitchenLineStatus, int] = {
    KitchenLineStatus.GETTING_READY: 0,
    KitchenLineStatus.READY_FOR_PICKUP: 1,
    KitchenLineStatus.PICKED_UP: 2,
}


def _validate_transition(current: KitchenLineStatus, new: KitchenLineStatus) -> None:
    if _STATUS_RANK[new] < _STATUS_RANK[current]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot move status backward from {current.value} to {new.value}",
        )


class KdsBoardService:
    def __init__(
        self,
        db: AsyncSession,
        redis: redis.Redis | None,
        max_rows: int = DEFAULT_BOARD_ROWS,
    ):
        self.db = db
        self.redis = redis
        self.max_rows = max(1, min(int(max_rows), MAX_BOARD_ROWS_CAP))

    @property
    def live_window_minutes(self) -> int:
        return LIVE_ORDERS_WINDOW_MINUTES

    def _live_orders_filter(self):
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=LIVE_ORDERS_WINDOW_MINUTES
        )
        has_incomplete_line = exists().where(
            OrderItem.order_id == Order.id,
            OrderItem.kitchen_status != KitchenLineStatus.PICKED_UP,
        )
        return (
            Order.payment_status == PaymentStatus.COMPLETED,
            or_(Order.created_at >= window_start, has_incomplete_line),
        )

    async def _load_live_orders(self) -> list[Order]:
        stmt = (
            select(Order)
            .where(*self._live_orders_filter())
            .options(selectinload(Order.line_items))
            .order_by(Order.created_at.asc())
            .limit(self.max_rows)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all())

    async def _clubbed_totals(self, order_ids: list[int]) -> list[dict[str, Any]]:
        if not order_ids:
            return []
        stmt = (
            select(OrderItem.item_name, func.sum(OrderItem.quantity).label("qty"))
            .where(
                OrderItem.order_id.in_(order_ids),
                OrderItem.kitchen_status != KitchenLineStatus.PICKED_UP,
            )
            .group_by(OrderItem.item_name)
            .order_by(func.sum(OrderItem.quantity).desc())
        )
        rows = (await self.db.execute(stmt)).all()
        out: list[dict[str, Any]] = []
        for name, qty in rows:
            if not name:
                continue
            out.append({"item_name": name, "quantity": int(qty or 0)})
        return out

    def _serialize_order(self, order: Order) -> dict[str, Any]:
        lines = sorted(order.line_items, key=lambda li: li.line_index)
        return {
            "id": order.id,
            "order_id": order.order_id,
            "kot_code": order.kot_code,
            "kot_number": order.kot_number,
            "kot_date": order.kot_date.isoformat() if order.kot_date else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "lines": [
                {
                    "id": li.id,
                    "line_index": li.line_index,
                    "sku_code": li.sku_code,
                    "item_name": li.item_name,
                    "quantity": li.quantity,
                    "kitchen_status": li.kitchen_status.value,
                }
                for li in lines
            ],
        }

    async def get_board_snapshot(self) -> dict[str, Any]:
        orders = await self._load_live_orders()
        order_ids = [o.id for o in orders]
        clubbed = await self._clubbed_totals(order_ids)
        return {
            "live_window_minutes": LIVE_ORDERS_WINDOW_MINUTES,
            "option": "B",
            "max_rows": self.max_rows,
            "orders": [self._serialize_order(o) for o in orders if o.line_items],
            "clubbed_totals": clubbed,
        }

    async def set_line_kitchen_status(
        self, line_id: int, new_status: KitchenLineStatus
    ) -> dict[str, Any]:
        stmt = (
            select(OrderItem)
            .join(Order)
            .where(OrderItem.id == line_id)
            .options(selectinload(OrderItem.order))
        )
        line = (await self.db.execute(stmt)).scalar_one_or_none()
        if not line:
            raise HTTPException(status_code=404, detail="Order line not found")

        order = line.order
        if order.payment_status != PaymentStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Order is not paid / not on kitchen board")

        _validate_transition(line.kitchen_status, new_status)
        line.kitchen_status = new_status
        await self.db.commit()
        await self.db.refresh(line)

        payload: dict[str, Any] = {
            "line_id": line.id,
            "order_id": order.order_id,
            "kot_code": order.kot_code,
            "item_name": line.item_name,
            "quantity": line.quantity,
            "kitchen_status": new_status.value,
        }
        await emit_kitchen_event(self.redis, "ITEM_STATUS_CHANGED", payload)

        if new_status == KitchenLineStatus.READY_FOR_PICKUP:
            speech = line_ready_speech(order.kot_code, line.item_name or "")
            await emit_kitchen_event(
                self.redis,
                "TMS_ANNOUNCE",
                {
                    **payload,
                    "speech": speech,
                },
            )

        await emit_kitchen_event(self.redis, "BOARD_REFRESH", {"reason": "line_status"})

        return payload
