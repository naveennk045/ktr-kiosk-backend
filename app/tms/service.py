"""TMS — token-centric snapshot for customer display (per store)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import Order, OrderItem, OrderItemStatus, PaymentStatus
from app.kds.constants import LIVE_ORDERS_WINDOW_MINUTES
from app.tms.menu_meta import match_menu_item
from app.tms.stats import DayStats, load_day_stats

TMS_TOKEN_LIMIT = 200


def _token_number(order: Order) -> str:
    """Short number for the board (``KTR-101`` → ``101``)."""
    if order.kot_number is not None:
        return str(order.kot_number)
    code = order.kot_code or ""
    return code.removeprefix("KTR-") or order.order_id


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _line_meta(item_name: str | None) -> dict[str, Any]:
    m = match_menu_item(item_name)
    if not m:
        return {"menu_id": None, "category": None, "image": None, "short": None}
    return {"menu_id": m["id"], "category": m["category"], "image": m["image"], "short": m["short"]}


def _board_state(lines: list[OrderItem]) -> str:
    """Card state on the board: received → cooking → partial → ready."""
    need_ready = sum(int(li.items_need_be_ready or 0) for li in lines)
    if need_ready == 0:
        return "ready"
    if any(int(li.items_need_be_ready or 0) < int(li.quantity or 0) for li in lines):
        return "partial"
    if any(li.order_status == OrderItemStatus.PREPARING for li in lines):
        return "cooking"
    return "received"


def _serialize_line(li: OrderItem, order: Order, day: DayStats) -> dict[str, Any]:
    meta = _line_meta(li.item_name)
    return {
        "id": li.id,
        "item_name": li.item_name,
        "quantity": li.quantity,
        "items_need_be_ready": int(getattr(li, "items_need_be_ready", 0) or 0),
        "items_need_be_collected": int(getattr(li, "items_need_be_collected", 0) or 0),
        "order_status": li.order_status.value,
        "preparing_at": _iso(getattr(li, "preparing_at", None)),
        "ready_at": _iso(getattr(li, "ready_at", None)),
        # Petpooja addons/customisations → "Made your way" on the board.
        "has_addons": bool(li.addon_items),
        **meta,
        "first_of_day": bool(
            meta["menu_id"] and day.first_order_for_item.get(meta["menu_id"]) == order.id
        ),
    }


def _order_milestone(order: Order) -> str | None:
    """Every 50th token of the day gets a tag on its card."""
    n = order.kot_number
    if n and n % 50 == 0:
        return f"{_ordinal(n)} order of the day"
    return None


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


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
        day = await load_day_stats(self.db, self.store_id)

        tokens: list[dict[str, Any]] = []
        for order in orders:
            if not order.line_items:
                continue
            lines = sorted(order.line_items, key=lambda li: li.id)
            any_ready = any(
                int(getattr(li, "items_need_be_collected", 0) or 0) > 0
                or li.order_status == OrderItemStatus.READY
                for li in lines
            )
            any_in_kitchen = any(
                int(getattr(li, "items_need_be_ready", 0) or 0) > 0
                or li.order_status
                in (OrderItemStatus.NOT_ACCEPTED, OrderItemStatus.PREPARING)
                for li in lines
            )
            tokens.append(
                {
                    "kot_code": order.kot_code,
                    "token_number": _token_number(order),
                    "order_id": order.order_id,
                    "order_type": order.order_type.value if order.order_type else None,
                    # Board column: any portion waiting at the counter puts the token in "Ready".
                    "display_state": "READY" if any_ready else "PREPARING",
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                    "milestone": _order_milestone(order),
                    "board_state": _board_state(lines),
                    "lines": [_serialize_line(li, order, day) for li in lines],
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
            # Clients offset their timers by this so TV clock drift doesn't skew "since order".
            "server_time": datetime.now(timezone.utc).isoformat(),
            "stats": {
                "orders_today": day.orders_today,
                "category_counts": day.category_counts,
                "on_board": len(tokens),
            },
            "tokens": tokens,
        }
