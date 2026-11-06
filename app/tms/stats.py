"""Day counters for the TMS board: header stats, "first of the day" tags and served milestones.

"Today" follows the KOT day (``orders.kot_date``), the same day boundary token numbers reset on.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order, OrderItem, PaymentStatus
from app.tms.menu_meta import GROUP_BY_CATEGORY, GROUPS, SERVED_STEP, match_menu_item


@dataclass
class DayStats:
    orders_today: int = 0
    # Units ordered today per menu category (e.g. "davangere" → 24).
    category_counts: dict[str, int] = field(default_factory=dict)
    # menu_id → orders.id of the first paid order today containing it.
    first_order_for_item: dict[str, int] = field(default_factory=dict)
    # Units that reached READY today, keyed by menu_id and by "g:<group>".
    served: dict[str, int] = field(default_factory=dict)


async def load_day_stats(db: AsyncSession, store_id: int, day: date | None = None) -> DayStats:
    day = day or date.today()
    stmt = (
        select(
            Order.id,
            OrderItem.item_name,
            OrderItem.quantity,
            OrderItem.items_need_be_ready,
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.store_id == store_id,
            Order.kot_date == day,
            Order.payment_status == PaymentStatus.COMPLETED,
        )
        .order_by(Order.created_at.asc(), OrderItem.id.asc())
    )
    rows = (await db.execute(stmt)).all()

    out = DayStats()
    order_ids: set[int] = set()
    cats: dict[str, int] = defaultdict(int)
    served: dict[str, int] = defaultdict(int)
    for order_pk, item_name, qty, need_ready in rows:
        order_ids.add(order_pk)
        m = match_menu_item(item_name)
        if not m:
            continue
        cats[m["category"]] += int(qty or 0)
        out.first_order_for_item.setdefault(m["id"], order_pk)
        done = max(0, int(qty or 0) - int(need_ready or 0))
        if done:
            served[m["id"]] += done
            group = GROUP_BY_CATEGORY.get(m["category"])
            if group:
                served[f"g:{group}"] += done
    out.orders_today = len(order_ids)
    out.category_counts = dict(cats)
    out.served = dict(served)
    return out


def served_milestones(
    served_after: dict[str, int], item_name: str | None, moved_qty: int
) -> list[dict[str, Any]]:
    """Milestones crossed by moving ``moved_qty`` units of ``item_name`` to READY.

    Group milestones ("100th filter coffee") sort ahead of single-dish ones; at most two fire.
    """
    m = match_menu_item(item_name)
    if not m or moved_qty <= 0:
        return []
    keys: list[tuple[str, str, str, str | None, bool]] = [
        (m["id"], m["name"], m["name"], m["image"], False)
    ]
    group = GROUP_BY_CATEGORY.get(m["category"])
    if group:
        g = GROUPS[group]
        keys.append((f"g:{group}", g["one"], g["many"], g["image"] or m["image"], True))

    hits: list[dict[str, Any]] = []
    for key, one, many, image, is_group in keys:
        after = served_after.get(key, 0)
        before = after - moved_qty
        if after // SERVED_STEP > before // SERVED_STEP:
            hits.append(
                {
                    "n": (after // SERVED_STEP) * SERVED_STEP,
                    "one": one,
                    "many": many,
                    "image": image,
                    "menu_id": m["id"],
                    "group": is_group,
                }
            )
    hits.sort(key=lambda h: (not h["group"], -h["n"]))
    return hits[:2]
