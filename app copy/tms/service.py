"""TMS — token-centric snapshot for customer display (pairs with KDS events)."""

from __future__ import annotations

from typing import Any

import redis.asyncio as redis
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import (
    KitchenLineStatus,
    Order,
    OrderItem,
    PaymentStatus,
)
from app.kds.constants import LIVE_ORDERS_WINDOW_MINUTES

TMS_TOKEN_LIMIT = 200


class TmsTokenService:
    def __init__(self, db: AsyncSession, redis: redis.Redis | None):
        self.db = db
        self.redis = redis

    @property
    def live_window_minutes(self) -> int:
        return LIVE_ORDERS_WINDOW_MINUTES

    def _visible_tokens_filter(self):
        """Paid orders with at least one line not yet picked up (token stays until all picked)."""
        has_incomplete_line = exists().where(
            OrderItem.order_id == Order.id,
            OrderItem.kitchen_status != KitchenLineStatus.PICKED_UP,
        )
        return (Order.payment_status == PaymentStatus.COMPLETED, has_incomplete_line)

    async def get_snapshot(self) -> dict[str, Any]:
        # Same Option B window as KDS; only tokens with at least one line not PICKED_UP.
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
            lines = sorted(order.line_items, key=lambda li: li.line_index)
            any_ready = any(
                li.kitchen_status == KitchenLineStatus.READY_FOR_PICKUP for li in lines
            )
            any_preparing = any(
                li.kitchen_status == KitchenLineStatus.GETTING_READY for li in lines
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
                            "kitchen_status": li.kitchen_status.value,
                        }
                        for li in lines
                    ],
                    "flags": {
                        "has_ready_for_pickup": any_ready,
                        "has_getting_ready": any_preparing,
                    },
                }
            )

        return {
            "live_window_minutes": LIVE_ORDERS_WINDOW_MINUTES,
            "option": "B",
            "tokens": tokens,
        }
