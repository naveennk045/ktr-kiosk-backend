"""TMS — token-centric snapshot for customer display (per store)."""

from __future__ import annotations

from typing import Any

import redis.asyncio as redis
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import Order, OrderItem, OrderItemStatus, PaymentStatus
from app.kds.constants import LIVE_ORDERS_WINDOW_MINUTES

TMS_TOKEN_LIMIT = 200


class TmsTokenService:
    def __init__(self, db: AsyncSession, redis: redis.Redis | None, store_id: int):
        self.db = db
        self.redis = redis
        self.store_id = store_id

    @property
    def live_window_minutes(self) -> int:
        return LIVE_ORDERS_WINDOW_MINUTES

    def _visible_tokens_filter(self):
        """Paid orders for this store with at least one line not yet collected."""
        has_open_line = exists().where(
            OrderItem.order_id == Order.id,
            OrderItem.order_status != OrderItemStatus.COLLECTED,
        )
        return (
            Order.store_id == self.store_id,
            Order.payment_status == PaymentStatus.COMPLETED,
            has_open_line,
        )

    async def get_snapshot(self) -> dict[str, Any]:
        stmt = (
            select(Order)
            .where(*self._visible_tokens_filter())
            .options(selectinload(Order.line_items))
            .order_by(Order.created_at.asc())
            .limit(TMS_TOKEN_LIMIT)
        )
        result = await self.db.execute(stmt)
        orders = list(result.scalars().unique().all())

        tokens: list[dict[str, Any]] = []
        for order in orders:
            if not order.line_items:
                continue
            lines = sorted(order.line_items, key=lambda li: li.id)
            any_ready = any(li.order_status == OrderItemStatus.READY for li in lines)
            any_in_kitchen = any(
                li.order_status in (OrderItemStatus.NOT_ACCEPTED, OrderItemStatus.PREPARING)
                for li in lines
            )
            tokens.append(
                {
                    "kot_code": order.kot_code,
                    "order_id": order.order_id,
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                    "lines": [
                        {
                            "id": li.id,
                            "item_name": li.item_name,
                            "quantity": li.quantity,
                            "order_status": li.order_status.value,
                        }
                        for li in lines
                    ],
                    "flags": {
                        "has_ready_for_pickup": any_ready,
                        "has_in_kitchen": any_in_kitchen,
                    },
                }
            )

        return {
            "store_id": self.store_id,
            "live_window_minutes": LIVE_ORDERS_WINDOW_MINUTES,
            "option": "B",
            "tokens": tokens,
        }
