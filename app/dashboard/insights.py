"""
Customer-behaviour insights for the admin dashboard (read-only).

Everything is computed with SQL aggregates over COMPLETED orders for the given store(s)
and IST period, using the same period rules as the other analytics endpoints
(`_time_filters_for_period`). The only non-SQL step is mapping SKUs to catalog categories,
because the catalog lives in Redis / the `menus` JSON, not in relational tables.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

import redis.asyncio as redis
from sqlalchemy import Date, and_, case, cast, desc, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.order import Order, OrderItem, OrderType, PaymentStatus
from app.dashboard.schemas import (
    DashboardPeriod,
    InsightsCategory,
    InsightsCustomisation,
    InsightsDailyPoint,
    InsightsDaypart,
    InsightsDaypartSplit,
    InsightsHabits,
    InsightsHeatCell,
    InsightsItem,
    InsightsKpis,
    InsightsMover,
    InsightsOrderTypeSide,
    InsightsOrderTypes,
    InsightsPair,
    InsightsPackedItem,
    InsightsResponse,
    InsightsSuggestion,
    InsightsWindow,
)
from app.dashboard.service import IST, _time_filters_for_period

logger = logging.getLogger(__name__)

IST_NAME = "Asia/Kolkata"
UNCATEGORIZED = "uncategorized"

# Day parts by IST hour of order creation: breakfast < 11, lunch 11–15, evening >= 16.
DAYPART_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch", "evening": "Evening"}
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

BEST_SELLER_LIMIT = 8
SLOW_MOVER_LIMIT = 6
PAIR_LIMIT = 6
CUSTOMISATION_LIMIT = 8
PACKED_ITEM_LIMIT = 5
# An item needs this many units across both periods before its % change is reported.
MOVER_MIN_UNITS = 6
MAX_SUGGESTIONS = 6


def _f(v) -> float:
    return round(float(v or 0), 2)


def _i(v) -> int:
    return int(v or 0)


def _pct(part, whole) -> float:
    return round(100.0 * float(part) / float(whole), 1) if whole else 0.0


def _daypart_of(hour: int) -> str:
    if hour < 11:
        return "breakfast"
    if hour < 16:
        return "lunch"
    return "evening"


def _hour_label(hour: int) -> str:
    if hour == 0:
        return "12 AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM" if hour > 12 else f"{hour} AM"


def _clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _ist_hour():
    return func.extract("hour", Order.created_at.op("AT TIME ZONE")(IST_NAME))


def _daypart_filters(daypart: InsightsDaypart) -> list:
    hour = _ist_hour()
    if daypart == "breakfast":
        return [hour < 11]
    if daypart == "lunch":
        return [hour >= 11, hour < 16]
    if daypart == "evening":
        return [hour >= 16]
    return []


def _window_bounds(
    period: DashboardPeriod,
    from_date: Optional[date],
    to_date: Optional[date],
    now: datetime,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Start (inclusive) and end (exclusive) of the period, mirroring `_time_filters_for_period`.

    `end` is capped at now. Either bound is None when the period is open-ended on that side.
    """
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return today_start, now
    if period == "yesterday":
        return today_start - timedelta(days=1), today_start
    if period == "last_week":
        return today_start - timedelta(days=7), now
    if period == "custom_range":
        start = (
            datetime(from_date.year, from_date.month, from_date.day, tzinfo=IST)
            if from_date
            else None
        )
        end = None
        if to_date:
            end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=IST) + timedelta(days=1)
            end = min(end, now)
        return start, end
    return None, None


def _calendar_days(start: datetime, end: datetime) -> int:
    """IST calendar days touched by [start, end)."""
    last = (end - timedelta(microseconds=1)).astimezone(IST).date()
    return max(1, (last - start.astimezone(IST).date()).days + 1)


class InsightsBuilder:
    def __init__(self, db: AsyncSession, store_ids: Sequence[int], redis_client: redis.Redis):
        self.db = db
        self.store_ids = list(store_ids)
        self.redis = redis_client

    # ─── shared pieces ────────────────────────────────────────────────────────

    def _base(self, time_filters: list) -> list:
        return [
            Order.store_id.in_(self.store_ids),
            Order.payment_status == PaymentStatus.COMPLETED,
            *time_filters,
        ]

    @staticmethod
    def _line_type():
        """Effective DINEIN / TAKEAWAY of a line (mixed orders store it per line)."""
        return func.coalesce(OrderItem.order_type, Order.order_type)

    async def _category_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        """sku -> category id and category id -> name, from each store's catalog."""
        from app.services.catalog_service import CatalogService

        sku_to_cat: dict[str, str] = {}
        cat_to_name: dict[str, str] = {}
        for store_id in self.store_ids:
            try:
                catalog = await CatalogService(self.redis, None, store_id).get_catalog(
                    channel="default", db=self.db
                )
            except Exception as e:
                logger.warning(f"Insights: no catalog for store {store_id}: {e}")
                continue
            for cat in catalog.get("categories", []):
                if "categoryId" in cat and "name" in cat:
                    cat_to_name.setdefault(str(cat["categoryId"]), cat["name"])
            for item in catalog.get("items", []):
                if "skuCode" in item and "categoryId" in item:
                    sku_to_cat.setdefault(str(item["skuCode"]), str(item["categoryId"]))
        return sku_to_cat, cat_to_name

    @staticmethod
    def _category_expr(sku_to_cat: dict[str, str]):
        """SQL CASE mapping a line's SKU to its catalog category id."""
        by_cat: dict[str, list[str]] = {}
        for sku, cat_id in sku_to_cat.items():
            by_cat.setdefault(cat_id, []).append(sku)
        if not by_cat:
            return literal(UNCATEGORIZED)
        return case(
            *[(OrderItem.item_skuid.in_(skus), cat_id) for cat_id, skus in by_cat.items()],
            else_=UNCATEGORIZED,
        )

    # ─── queries ──────────────────────────────────────────────────────────────

    async def _order_totals(self, base: list):
        amt = Order.total_amount_include_tax
        dine = Order.order_type == OrderType.DINEIN
        take = Order.order_type == OrderType.TAKEAWAY
        stmt = select(
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(amt), 0).label("revenue"),
            func.coalesce(func.sum(case((dine, 1), else_=0)), 0).label("dine_orders"),
            func.coalesce(func.sum(case((take, 1), else_=0)), 0).label("take_orders"),
            func.coalesce(func.sum(case((dine, amt), else_=0)), 0).label("dine_revenue"),
            func.coalesce(func.sum(case((take, amt), else_=0)), 0).label("take_revenue"),
            func.coalesce(func.sum(Order.takeaway_charges_include_tax), 0).label("takeaway_charges"),
            func.coalesce(
                func.sum(case((Order.is_discount_applied.is_(True), 1), else_=0)), 0
            ).label("discount_orders"),
        ).where(*base)
        return (await self.db.execute(stmt)).one()

    async def _basket_totals(self, base: list):
        """Per-order basket facts (one row per order in a subquery), then aggregated."""
        line_type = self._line_type()
        has_options = func.jsonb_array_length(OrderItem.options) > 0
        has_note = and_(OrderItem.note.isnot(None), OrderItem.note != "")
        has_addon = func.jsonb_array_length(OrderItem.addon_items) > 0
        kitchen_line = OrderItem.preparing_at.isnot(None)

        per_order = (
            select(
                OrderItem.order_id.label("order_pk"),
                func.sum(OrderItem.quantity).label("units"),
                func.sum(case((line_type == OrderType.TAKEAWAY, OrderItem.quantity), else_=0)).label("take_units"),
                func.bool_or(line_type == OrderType.TAKEAWAY).label("any_take"),
                func.bool_or(line_type == OrderType.DINEIN).label("any_dine"),
                func.bool_or(or_(has_options, has_note, has_addon)).label("customised"),
                func.bool_or(has_options).label("with_options"),
                func.bool_or(has_note).label("with_note"),
                func.bool_or(has_addon).label("with_addon"),
                # Kitchen time: paid (first line sent to the kitchen) until the last line is ready.
                # Only for orders where every kitchen line has been marked ready.
                func.count().filter(kitchen_line).label("kitchen_lines"),
                func.count().filter(and_(kitchen_line, OrderItem.ready_at.is_(None))).label("unready_lines"),
                func.extract(
                    "epoch",
                    func.max(OrderItem.ready_at).filter(kitchen_line)
                    - func.min(OrderItem.preparing_at),
                ).label("ready_seconds"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(*base)
            .group_by(OrderItem.order_id)
            .subquery()
        )
        c = per_order.c
        timed = and_(c.kitchen_lines > 0, c.unready_lines == 0, c.ready_seconds >= 0)
        stmt = select(
            func.coalesce(func.sum(c.units), 0).label("units"),
            func.coalesce(func.sum(c.take_units), 0).label("take_units"),
            func.count().filter(c.units > 1).label("multi_item_orders"),
            func.count().filter(c.customised).label("customised_orders"),
            func.count().filter(c.with_options).label("option_orders"),
            func.count().filter(c.with_note).label("note_orders"),
            func.count().filter(c.with_addon).label("addon_orders"),
            func.count().filter(and_(c.any_take, c.any_dine)).label("mixed_orders"),
            func.count().filter(timed).label("timed_orders"),
            func.avg(c.ready_seconds).filter(timed).label("ready_avg"),
            func.percentile_cont(0.5).within_group(c.ready_seconds).filter(timed).label("ready_median"),
        )
        return (await self.db.execute(stmt)).one()

    async def _heat_rows(self, base: list):
        local = Order.created_at.op("AT TIME ZONE")(IST_NAME)
        stmt = (
            select(
                func.extract("dow", local).label("weekday"),
                func.extract("hour", local).label("hour"),
                func.count(Order.id).label("orders"),
                func.coalesce(
                    func.sum(case((Order.order_type == OrderType.TAKEAWAY, 1), else_=0)), 0
                ).label("take_orders"),
            )
            .where(*base)
            .group_by("weekday", "hour")
        )
        return (await self.db.execute(stmt)).all()

    async def _daily_rows(self, base: list):
        stmt = (
            select(
                cast(Order.created_at.op("AT TIME ZONE")(IST_NAME), Date).label("order_date"),
                func.count(Order.id).label("orders"),
                func.coalesce(func.sum(Order.total_amount_include_tax), 0).label("revenue"),
            )
            .where(*base)
            .group_by("order_date")
            .order_by("order_date")
        )
        return (await self.db.execute(stmt)).all()

    async def _item_rows(self, base: list):
        stmt = (
            select(
                OrderItem.item_skuid.label("sku"),
                func.max(OrderItem.item_name).label("item_name"),
                func.sum(OrderItem.quantity).label("quantity"),
                func.sum(OrderItem.price * OrderItem.quantity).label("revenue"),
                func.count(OrderItem.order_id.distinct()).label("order_count"),
                func.sum(
                    case((self._line_type() == OrderType.TAKEAWAY, OrderItem.quantity), else_=0)
                ).label("take_quantity"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(*base)
            .group_by(OrderItem.item_skuid)
            .order_by(desc("quantity"), "sku")
        )
        return (await self.db.execute(stmt)).all()

    async def _category_rows(self, base: list, cat_expr):
        timed = and_(OrderItem.preparing_at.isnot(None), OrderItem.ready_at.isnot(None))
        stmt = (
            select(
                cat_expr.label("category_id"),
                func.sum(OrderItem.quantity).label("quantity"),
                func.sum(OrderItem.price * OrderItem.quantity).label("revenue"),
                func.count(OrderItem.order_id.distinct()).label("order_count"),
                func.count().filter(timed).label("timed_lines"),
                func.avg(
                    func.extract("epoch", OrderItem.ready_at - OrderItem.preparing_at)
                ).filter(timed).label("ready_avg"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(*base)
            .group_by("category_id")
        )
        return (await self.db.execute(stmt)).all()

    async def _pair_rows(self, base: list):
        a = aliased(OrderItem)
        b = aliased(OrderItem)
        both = func.count(a.order_id.distinct())
        stmt = (
            select(
                a.item_skuid.label("sku_a"),
                func.max(a.item_name).label("item_a"),
                b.item_skuid.label("sku_b"),
                func.max(b.item_name).label("item_b"),
                both.label("orders"),
            )
            .select_from(a)
            .join(b, and_(a.order_id == b.order_id, a.item_skuid < b.item_skuid))
            .join(Order, Order.id == a.order_id)
            .where(*base)
            .group_by(a.item_skuid, b.item_skuid)
            .order_by(desc(both), a.item_skuid, b.item_skuid)
            .limit(PAIR_LIMIT)
        )
        return (await self.db.execute(stmt)).all()

    async def _option_rows(self, base: list, cat_expr):
        opt = func.jsonb_array_elements_text(OrderItem.options).table_valued("value").alias("opt")
        stmt = (
            select(
                opt.c.value.label("option"),
                cat_expr.label("category_id"),
                func.sum(OrderItem.quantity).label("quantity"),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .join(opt, true())
            .where(*base)
            .group_by(opt.c.value, "category_id")
        )
        return (await self.db.execute(stmt)).all()

    # ─── assembly ─────────────────────────────────────────────────────────────

    @staticmethod
    def _kpis(orders_row, basket_row) -> InsightsKpis:
        orders = _i(orders_row.orders)
        revenue = _f(orders_row.revenue)
        units = _i(basket_row.units)
        timed = _i(basket_row.timed_orders)
        return InsightsKpis(
            orders=orders,
            revenue=revenue,
            avg_order_value=round(revenue / orders, 2) if orders else 0.0,
            units=units,
            items_per_order=round(units / orders, 2) if orders else 0.0,
            takeaway_orders=_i(orders_row.take_orders),
            takeaway_share_pct=_pct(orders_row.take_orders, orders),
            timed_orders=timed,
            ready_seconds_avg=round(float(basket_row.ready_avg), 1) if timed else None,
            ready_seconds_median=round(float(basket_row.ready_median), 1) if timed else None,
        )

    async def build(
        self,
        period: DashboardPeriod,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        daypart: InsightsDaypart = "all",
    ) -> InsightsResponse:
        now = datetime.now(IST)
        part_filters = _daypart_filters(daypart)
        base = self._base([*_time_filters_for_period(period, from_date, to_date), *part_filters])

        # Previous period: the same number of IST calendar days immediately before, cut off at
        # the same time of day (so "today so far" is compared with "yesterday up to this time").
        start, end = _window_bounds(period, from_date, to_date, now)
        prev_base = None
        prev_window = None
        days = None
        if start is not None and end is not None and end > start:
            days = _calendar_days(start, end)
            shift = timedelta(days=days)
            prev_base = self._base(
                [Order.created_at >= start - shift, Order.created_at < end - shift, *part_filters]
            )
            prev_window = InsightsWindow(start=start - shift, end=end - shift, days=days)

        orders_row = await self._order_totals(base)
        basket_row = await self._basket_totals(base)
        kpis = self._kpis(orders_row, basket_row)

        previous_kpis = None
        prev_item_qty: dict[str, int] = {}
        prev_item_name: dict[str, str] = {}
        if prev_base is not None:
            previous_kpis = self._kpis(
                await self._order_totals(prev_base), await self._basket_totals(prev_base)
            )
            for r in await self._item_rows(prev_base):
                prev_item_qty[r.sku] = _i(r.quantity)
                prev_item_name[r.sku] = r.item_name

        daily_rows = await self._daily_rows(base)
        if days is None and daily_rows:
            # Open-ended period (all time): span from the first order day to the window end.
            first = daily_rows[0].order_date
            last = (end - timedelta(microseconds=1)).astimezone(IST).date() if end else now.date()
            days = max(1, (last - first).days + 1)
        window = InsightsWindow(start=start, end=end or now, days=days or 1)

        # One point per IST day across the window (zero-filled), so the trend has no gaps.
        by_day = {r.order_date: r for r in daily_rows}
        daily: list[InsightsDailyPoint] = []
        if daily_rows or start is not None:
            first_day = start.astimezone(IST).date() if start is not None else daily_rows[0].order_date
            last_day = ((end or now) - timedelta(microseconds=1)).astimezone(IST).date()
            if daily_rows:
                first_day = min(first_day, daily_rows[0].order_date)
                last_day = max(last_day, daily_rows[-1].order_date)
            day = first_day
            while day <= last_day:
                r = by_day.get(day)
                daily.append(
                    InsightsDailyPoint(
                        date=day, orders=_i(r.orders) if r else 0, revenue=_f(r.revenue) if r else 0.0
                    )
                )
                day += timedelta(days=1)

        # ── order types ──
        dine_orders = _i(orders_row.dine_orders)
        take_orders = _i(orders_row.take_orders)
        dine_units = kpis.units - _i(basket_row.take_units)
        take_units = _i(basket_row.take_units)

        heat_rows = await self._heat_rows(base)
        part_totals = {k: [0, 0] for k in DAYPART_LABELS}
        heatmap = []
        for r in heat_rows:
            hour = _i(r.hour)
            heatmap.append(InsightsHeatCell(weekday=_i(r.weekday), hour=hour, orders=_i(r.orders)))
            bucket = part_totals[_daypart_of(hour)]
            bucket[0] += _i(r.orders)
            bucket[1] += _i(r.take_orders)
        heatmap.sort(key=lambda c: (c.weekday, c.hour))

        item_rows = await self._item_rows(base)
        items = [
            InsightsItem(
                sku=r.sku,
                item_name=r.item_name or "Item",
                quantity=_i(r.quantity),
                revenue=_f(r.revenue),
                order_count=_i(r.order_count),
                previous_quantity=prev_item_qty.get(r.sku, 0) if prev_base is not None else None,
            )
            for r in item_rows
        ]
        packed = sorted(
            (r for r in item_rows if _i(r.take_quantity) > 0),
            key=lambda r: (-_i(r.take_quantity), r.sku),
        )[:PACKED_ITEM_LIMIT]

        order_types = InsightsOrderTypes(
            dine_in=InsightsOrderTypeSide(
                orders=dine_orders,
                revenue=_f(orders_row.dine_revenue),
                units=dine_units,
                avg_order_value=round(_f(orders_row.dine_revenue) / dine_orders, 2) if dine_orders else 0.0,
            ),
            takeaway=InsightsOrderTypeSide(
                orders=take_orders,
                revenue=_f(orders_row.take_revenue),
                units=take_units,
                avg_order_value=round(_f(orders_row.take_revenue) / take_orders, 2) if take_orders else 0.0,
            ),
            by_daypart=[
                InsightsDaypartSplit(
                    daypart=k,
                    orders=v[0],
                    takeaway_orders=v[1],
                    takeaway_share_pct=_pct(v[1], v[0]),
                )
                for k, v in part_totals.items()
            ],
            top_takeaway_items=[
                InsightsPackedItem(sku=r.sku, item_name=r.item_name or "Item", quantity=_i(r.take_quantity))
                for r in packed
            ],
            takeaway_charges_total=_f(orders_row.takeaway_charges),
            mixed_orders=_i(basket_row.mixed_orders),
        )

        # ── items: best / slow / movers ──
        best_sellers = items[:BEST_SELLER_LIMIT]
        slow_movers = (
            sorted(items[BEST_SELLER_LIMIT:], key=lambda x: (x.quantity, x.sku))[:SLOW_MOVER_LIMIT]
            if len(items) > BEST_SELLER_LIMIT
            else []
        )

        movers: list[InsightsMover] = []
        if prev_base is not None:
            cur_qty = {x.sku: x for x in items}
            for sku in set(cur_qty) | set(prev_item_qty):
                q = cur_qty[sku].quantity if sku in cur_qty else 0
                pq = prev_item_qty.get(sku, 0)
                if q + pq < MOVER_MIN_UNITS:
                    continue
                movers.append(
                    InsightsMover(
                        sku=sku,
                        item_name=cur_qty[sku].item_name if sku in cur_qty else prev_item_name.get(sku) or "Item",
                        quantity=q,
                        previous_quantity=pq,
                        # No % when the item did not sell at all in the previous period.
                        change_pct=round(100.0 * (q - pq) / pq, 1) if pq else None,
                    )
                )
            movers.sort(
                key=lambda m: (-(m.change_pct if m.change_pct is not None else float("inf")), -m.quantity, m.sku)
            )

        # ── categories, customisations ──
        sku_to_cat, cat_to_name = await self._category_maps()
        cat_expr = self._category_expr(sku_to_cat)
        item_revenue_total = sum(x.revenue for x in items)
        cat_qty: dict[str, int] = {}
        categories = []
        for r in await self._category_rows(base, cat_expr):
            cat_qty[r.category_id] = _i(r.quantity)
            timed_lines = _i(r.timed_lines)
            categories.append(
                InsightsCategory(
                    category_id=r.category_id,
                    category_name=cat_to_name.get(r.category_id, "Uncategorized"),
                    quantity=_i(r.quantity),
                    revenue=_f(r.revenue),
                    revenue_share_pct=_pct(r.revenue or 0, item_revenue_total),
                    order_count=_i(r.order_count),
                    order_share_pct=_pct(r.order_count, kpis.orders),
                    timed_lines=timed_lines,
                    ready_seconds_avg=round(float(r.ready_avg), 1) if timed_lines else None,
                )
            )
        categories.sort(key=lambda x: (-x.revenue, x.category_id))

        customisations = [
            InsightsCustomisation(
                option=r.option,
                category_id=r.category_id,
                category_name=cat_to_name.get(r.category_id, "Uncategorized"),
                quantity=_i(r.quantity),
                share_pct=_pct(r.quantity, cat_qty.get(r.category_id, 0)),
            )
            for r in await self._option_rows(base, cat_expr)
        ]
        # Most-used first (ranking by share alone lets one-off items in tiny categories dominate).
        customisations.sort(key=lambda x: (-x.quantity, -x.share_pct, x.option, x.category_id))
        customisations = customisations[:CUSTOMISATION_LIMIT]

        pairs = [
            InsightsPair(
                sku_a=r.sku_a,
                item_a=r.item_a or "Item",
                sku_b=r.sku_b,
                item_b=r.item_b or "Item",
                orders=_i(r.orders),
                share_pct=_pct(r.orders, kpis.orders),
            )
            for r in await self._pair_rows(base)
        ]

        habits = InsightsHabits(
            orders=kpis.orders,
            multi_item_orders=_i(basket_row.multi_item_orders),
            customised_orders=_i(basket_row.customised_orders),
            option_orders=_i(basket_row.option_orders),
            note_orders=_i(basket_row.note_orders),
            addon_orders=_i(basket_row.addon_orders),
            discount_orders=_i(orders_row.discount_orders),
        )

        response = InsightsResponse(
            period=period,
            from_date=from_date,
            to_date=to_date,
            daypart=daypart,
            store_ids=self.store_ids,
            window=window,
            previous_window=prev_window,
            kpis=kpis,
            previous_kpis=previous_kpis,
            order_types=order_types,
            best_sellers=best_sellers,
            slow_movers=slow_movers,
            movers=movers,
            categories=categories,
            category_mapping_available=bool(sku_to_cat),
            heatmap=heatmap,
            daily=daily,
            habits=habits,
            pairs=pairs,
            customisations=customisations,
            suggestions=[],
        )
        response.suggestions = build_suggestions(response)
        return response


def build_suggestions(d: InsightsResponse) -> list[InsightsSuggestion]:
    """Plain rule-based tips from the aggregates above. No tip is emitted without real data behind it."""
    tips: list[InsightsSuggestion] = []
    k = d.kpis
    if not k.orders:
        return tips
    days = max(1, d.window.days)

    def add(kind: str, text: str) -> None:
        tips.append(InsightsSuggestion(kind=kind, text=text))

    if d.best_sellers:
        top = d.best_sellers[0]
        add(
            "star",
            f"{top.item_name} is your best seller ({top.quantity} sold, about "
            f"{top.quantity / days:.1f} a day). Keep it prominent on the kiosk and never let it run short.",
        )

    peak = max(d.heatmap, key=lambda c: c.orders, default=None)
    if peak and peak.orders >= 3:
        add(
            "clock",
            f"Busiest slot: {WEEKDAYS[peak.weekday]} around {_hour_label(peak.hour)} "
            f"({peak.orders} orders). Staff up and prep ahead of it.",
        )

    rising = [m for m in d.movers if m.change_pct is not None and m.change_pct >= 25]
    if rising:
        m = rising[0]
        add(
            "up",
            f"{m.item_name} is rising fast (+{m.change_pct:.0f}%, {m.previous_quantity} → {m.quantity}). "
            "Make sure there is stock and staff ready for it.",
        )
    falling = [m for m in d.movers if m.change_pct is not None and m.change_pct <= -25]
    if falling:
        m = falling[-1]
        add(
            "warn",
            f"{m.item_name} is falling ({m.change_pct:.0f}%, {m.previous_quantity} → {m.quantity}). "
            "Check quality and availability, or feature it for a few days.",
        )

    if len(d.slow_movers) >= 2:
        a, b = d.slow_movers[0], d.slow_movers[1]
        add(
            "warn",
            f"{a.item_name} and {b.item_name} sell the least ({a.quantity} and {b.quantity} sold). "
            "Try them as a special of the day, or review whether they earn their place on the menu.",
        )

    if k.ready_seconds_median is not None and k.timed_orders >= 5 and k.ready_seconds_median > 12 * 60:
        slowest = max(
            (c for c in d.categories if c.ready_seconds_avg is not None),
            key=lambda c: c.ready_seconds_avg,
            default=None,
        )
        tail = f" {slowest.category_name} is the slowest category." if slowest else ""
        add(
            "warn",
            f"A typical order takes {_clock(k.ready_seconds_median)} from payment to ready.{tail}",
        )

    if d.pairs and d.pairs[0].orders >= 3:
        p = d.pairs[0]
        add(
            "idea",
            f"{p.item_a} and {p.item_b} are ordered together in {p.share_pct:.0f}% of orders. "
            "Offer them as a combo or suggest one when the other is added.",
        )

    single = k.orders - d.habits.multi_item_orders
    if k.orders >= 10 and _pct(single, k.orders) >= 50:
        add(
            "up",
            f"{_pct(single, k.orders):.0f}% of orders are a single item. "
            "An add-on prompt at checkout (a drink or a side) is the easiest way to lift the average order.",
        )

    busy_parcel = max(
        (p for p in d.order_types.by_daypart if p.orders >= 5),
        key=lambda p: p.takeaway_share_pct,
        default=None,
    )
    if busy_parcel and busy_parcel.takeaway_share_pct >= 40:
        add(
            "idea",
            f"{busy_parcel.takeaway_share_pct:.0f}% of {DAYPART_LABELS[busy_parcel.daypart].lower()} orders "
            "are takeaway. Keep packing material stocked and a packing hand free in that window.",
        )

    common = [c for c in d.customisations if c.share_pct >= 20 and c.quantity >= 5]
    if common:
        c = max(common, key=lambda c: c.share_pct)
        add(
            "idea",
            f"\"{c.option}\" is chosen on {c.share_pct:.0f}% of {c.category_name} items. "
            "Consider making it the default or a one-tap choice.",
        )

    if d.previous_kpis and d.previous_kpis.orders >= 5 and d.previous_kpis.avg_order_value:
        change = 100.0 * (k.avg_order_value - d.previous_kpis.avg_order_value) / d.previous_kpis.avg_order_value
        if abs(change) >= 10:
            add(
                "up" if change > 0 else "warn",
                f"Average order value is {'up' if change > 0 else 'down'} {abs(change):.0f}% on the previous period "
                f"(₹{d.previous_kpis.avg_order_value:,.0f} → ₹{k.avg_order_value:,.0f}).",
            )

    return tips[:MAX_SUGGESTIONS]
