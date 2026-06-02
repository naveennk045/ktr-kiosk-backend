import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import redis.asyncio as redis
from sqlalchemy import select, func, desc, asc, case, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import Order, OrderItem, PaymentStatus, OrderType, PaymentMethod, KdsStatus
from app.dashboard.schemas import (
    AnalyticsSummaryResponse,
    DashboardPeriod,
    OrderGridResponse,
    OrderGridItem,
    OrderDetailResponse,
    ItemRankEntry,
    ItemTopResponse,
    ItemDailyCount,
    ItemDailyResponse,
    ItemSummaryEntry,
    ItemSummaryResponse,
    CategoryItemEntry,
    CategorySummaryEntry,
    CategorySummaryResponse,
)

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _time_filters_for_period(
    period: DashboardPeriod,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list:
    """IST calendar boundaries. last_week = from 00:00 seven days ago through now.
    For custom_range, from_date (inclusive 00:00 IST) and to_date (inclusive 23:59:59 IST)
    are used. If only one bound is supplied, the other is open-ended.
    """
    now = datetime.now(IST)
    if period == "all_time":
        return []
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [Order.created_at >= start]
    if period == "yesterday":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        return [Order.created_at >= yesterday_start, Order.created_at < today_start]
    if period == "last_week":
        start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [Order.created_at >= start]
    if period == "custom_range":
        filters = []
        if from_date:
            start_dt = datetime(from_date.year, from_date.month, from_date.day, 0, 0, 0, tzinfo=IST)
            filters.append(Order.created_at >= start_dt)
        if to_date:
            end_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, 999999, tzinfo=IST)
            filters.append(Order.created_at <= end_dt)
        return filters
    raise ValueError(f"Unknown period: {period}")


class DashboardService:
    def __init__(self, db: AsyncSession, store_id: int, redis_client: redis.Redis):
        self.db = db
        self.store_id = store_id
        self.redis = redis_client

    async def get_analytics_summary(
        self,
        period: DashboardPeriod,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> AnalyticsSummaryResponse:
        time_filters = _time_filters_for_period(period, from_date, to_date)
        base = [
            Order.store_id == self.store_id,
            Order.payment_status == PaymentStatus.COMPLETED,
            *time_filters,
        ]

        amt = Order.total_amount_include_tax
        stmt = select(
            func.coalesce(func.sum(amt), 0),
            func.count(Order.id),
            func.coalesce(
                func.sum(case((Order.order_type == OrderType.DINEIN, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Order.order_type == OrderType.TAKEAWAY, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Order.payment_method == PaymentMethod.QR, amt), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Order.payment_method == PaymentMethod.CARD, amt), else_=0)), 0
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Order.payment_method.in_(
                                (PaymentMethod.CASH, PaymentMethod.MANUAL)
                            ),
                            amt,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(*base)

        row = (await self.db.execute(stmt)).one()
        (
            total_revenue,
            total_orders,
            dine_in,
            take_away,
            upi,
            card,
            cash,
        ) = row

        def _f(v) -> float:
            return float(v or 0)

        return AnalyticsSummaryResponse(
            period=period,
            from_date=from_date,
            to_date=to_date,
            totalRevenue=_f(total_revenue),
            totalOrders=int(total_orders or 0),
            dineInOrders=int(dine_in or 0),
            takeAwayOrders=int(take_away or 0),
            upiRupees=_f(upi),
            cardRupees=_f(card),
            cashRupees=_f(cash),
        )

    async def get_orders_grid(
        self,
        page: int,
        size: int,
        sort_by: str,
        sort_dir: str,
        period: DashboardPeriod,
        status: Optional[str] = None,
        search: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        order_type: Optional[OrderType] = None,
        payment_status: Optional[PaymentStatus] = None,
        payment_method: Optional[PaymentMethod] = None,
        kds_status: Optional[KdsStatus] = None,
        channel: Optional[str] = None,
        terminal_id: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
    ) -> OrderGridResponse:

        # Base Query
        stmt = (
            select(Order)
            .options(selectinload(Order.line_items))
            .where(Order.store_id == self.store_id)
        )

        for cond in _time_filters_for_period(period, from_date, to_date):
            stmt = stmt.where(cond)

        # Filtering
        if status:
            stmt = stmt.where(Order.payment_status == status)
        if payment_status:
            stmt = stmt.where(Order.payment_status == payment_status)
        if order_type:
            stmt = stmt.where(Order.order_type == order_type)
        if payment_method:
            stmt = stmt.where(Order.payment_method == payment_method)
        if kds_status:
            stmt = stmt.where(Order.kds_status == kds_status)
        if channel:
            stmt = stmt.where(Order.channel.ilike(f"%{channel}%"))
        if terminal_id:
            stmt = stmt.where(Order.terminal_id == terminal_id)
        if min_amount is not None:
            stmt = stmt.where(Order.total_amount_include_tax >= min_amount)
        if max_amount is not None:
            stmt = stmt.where(Order.total_amount_include_tax <= max_amount)
        if start_at:
            stmt = stmt.where(Order.created_at >= start_at)
        if end_at:
            stmt = stmt.where(Order.created_at <= end_at)

        if search:
            search_term = f"%{search}%"
            stmt = stmt.where(
                (Order.order_id.ilike(search_term)) | (Order.kot_code.ilike(search_term))
            )

        # Counting for pagination
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_elements = (await self.db.execute(count_stmt)).scalar() or 0
        total_pages = (total_elements + size - 1) // size

        # Sorting
        sort_column = getattr(Order, "created_at", Order.created_at) # Default
        if sort_by == "total_amount":
            sort_column = Order.total_amount_include_tax
        elif sort_by == "created_at":
            sort_column = Order.created_at

        if sort_dir.lower() == "asc":
            stmt = stmt.order_by(asc(sort_column))
        else:
            stmt = stmt.order_by(desc(sort_column))

        # Pagination
        stmt = stmt.offset(page * size).limit(size)

        result = await self.db.execute(stmt)
        orders = result.scalars().all()

        content = []
        for o in orders:
            item_names = []
            lines = list(o.line_items) if o.line_items else []
            if lines:
                for li in sorted(lines, key=lambda x: x.id):
                    item_names.append(li.item_name or "Item")
            else:
                for i in o.items or []:
                    if not isinstance(i, dict):
                        continue
                    item_names.append(
                        i.get("item_name") or i.get("name") or "Item"
                    )
            summary_text = item_names[0] if item_names else "No Items"
            if len(item_names) > 1:
                summary_text += f" (+{len(item_names)-1} more)"

            pay = o.payment_method
            payment_type = pay.value if pay is not None else None

            content.append(OrderGridItem(
                orderRefId=o.order_id,
                orderId=o.order_id,
                kotCode=o.kot_code,
                orderType=o.order_type,
                paymentType=payment_type,
                location=o.channel,
                amount=float(o.total_amount_include_tax),
                paymentStatus=o.payment_status,
                erpStatus=o.kds_status,
                itemsSummary=summary_text,
                createdAt=o.created_at,
            ))

        return OrderGridResponse(
            content=content,
            totalPages=total_pages,
            totalElements=total_elements
        )

    async def get_order_detail(self, order_id: str) -> Optional[OrderDetailResponse]:
        stmt = (
            select(Order)
            .options(selectinload(Order.line_items))
            .where(
                Order.order_id == order_id,
                Order.store_id == self.store_id,
            )
        )
        order = (await self.db.execute(stmt)).scalar_one_or_none()

        if not order:
            return None

        if order.line_items:
            detail_items = [
                {
                    "name": li.item_name,
                    "qty": li.quantity,
                    "price": float(li.price),
                    "sku": li.item_skuid,
                    "order_status": li.order_status.value,
                }
                for li in sorted(order.line_items, key=lambda x: x.id)
            ]
        else:
            detail_items = order.items

        # Build detailed response
        return OrderDetailResponse(
            orderRefId=order.order_id,
            location=order.channel,
            amount=float(order.total_amount_include_tax),
            paymentStatus=order.payment_status,
            erpStatus=order.kds_status,
            items=detail_items,
            paymentMeta=order.provider_resp,
            createdAt=order.created_at,
            takeaway_charges_without_tax=float(
                getattr(order, "takeaway_charges_exclude_tax", 0) or 0
            ),
            takeaway_charges_with_tax=float(
                getattr(order, "takeaway_charges_include_tax", 0) or 0
            ),
            cash_collected_by_staff_name=getattr(
                order, "cash_collected_by_staff_name", None
            ),
        )

    # ─── Item-wise Analytics ───────────────────────────────────────────────────────────

    def _item_base_join(self, time_filters: list):
        """Common join: order_items ➡ orders (COMPLETED, this store, time window)."""
        stmt = (
            select(
                OrderItem.item_skuid.label("sku"),
                OrderItem.item_name.label("item_name"),
                func.sum(OrderItem.quantity).label("total_quantity"),
                func.sum(OrderItem.price * OrderItem.quantity).label("total_revenue"),
                func.count(OrderItem.order_id.distinct()).label("order_count"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.store_id == self.store_id,
                Order.payment_status == PaymentStatus.COMPLETED,
                *time_filters,
            )
            .group_by(OrderItem.item_skuid, OrderItem.item_name)
        )
        return stmt

    async def get_top_items(
        self, period: DashboardPeriod, limit: int = 10,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> ItemTopResponse:
        """Return the top `limit` items ranked by total quantity sold in the period."""
        time_filters = _time_filters_for_period(period, from_date, to_date)
        stmt = self._item_base_join(time_filters).order_by(desc("total_quantity")).limit(limit)

        rows = (await self.db.execute(stmt)).all()
        items = [
            ItemRankEntry(
                sku=r.sku,
                item_name=r.item_name,
                total_quantity=int(r.total_quantity or 0),
                total_revenue=float(r.total_revenue or 0),
                order_count=int(r.order_count or 0),
            )
            for r in rows
        ]
        return ItemTopResponse(period=period, from_date=from_date, to_date=to_date, limit=limit, items=items)

    async def get_daily_item_counts(
        self, period: DashboardPeriod, sku: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> ItemDailyResponse:
        """
        Return per-day, per-item quantity totals.
        If `sku` is provided, filter to that single item only.
        """
        time_filters = _time_filters_for_period(period, from_date, to_date)

        stmt = (
            select(
                cast(Order.created_at.op("AT TIME ZONE")("Asia/Kolkata"), Date).label("order_date"),
                OrderItem.item_skuid.label("sku"),
                OrderItem.item_name.label("item_name"),
                func.sum(OrderItem.quantity).label("total_quantity"),
                func.count(OrderItem.order_id.distinct()).label("order_count"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.store_id == self.store_id,
                Order.payment_status == PaymentStatus.COMPLETED,
                *time_filters,
            )
            .group_by("order_date", OrderItem.item_skuid, OrderItem.item_name)
            .order_by("order_date", desc("total_quantity"))
        )

        if sku:
            stmt = stmt.where(OrderItem.item_skuid == sku)

        rows = (await self.db.execute(stmt)).all()
        daily_rows = [
            ItemDailyCount(
                date=r.order_date,
                sku=r.sku,
                item_name=r.item_name,
                total_quantity=int(r.total_quantity or 0),
                order_count=int(r.order_count or 0),
            )
            for r in rows
        ]
        return ItemDailyResponse(period=period, from_date=from_date, to_date=to_date, sku_filter=sku, rows=daily_rows)

    async def get_item_summary(
        self, period: DashboardPeriod,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> ItemSummaryResponse:
        """Full per-item stats: qty, revenue, orders, avg qty/order — all COMPLETED orders."""
        time_filters = _time_filters_for_period(period, from_date, to_date)
        stmt = self._item_base_join(time_filters).order_by(desc("total_quantity"))

        rows = (await self.db.execute(stmt)).all()

        items = []
        total_items_sold = 0
        for r in rows:
            qty = int(r.total_quantity or 0)
            orders = int(r.order_count or 0)
            total_items_sold += qty
            items.append(
                ItemSummaryEntry(
                    sku=r.sku,
                    item_name=r.item_name,
                    total_quantity=qty,
                    total_revenue=float(r.total_revenue or 0),
                    order_count=orders,
                    avg_quantity_per_order=round(qty / orders, 2) if orders else 0.0,
                )
            )

        return ItemSummaryResponse(
            period=period,
            from_date=from_date,
            to_date=to_date,
            total_items_sold=total_items_sold,
            unique_items=len(items),
            items=items,
        )

    async def get_category_summary(
        self,
        period: DashboardPeriod,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> CategorySummaryResponse:
        from app.services.catalog_service import CatalogService
        
        # 1. Get time filters
        time_filters = _time_filters_for_period(period, from_date, to_date)
        
        # 2. Query raw order item sales
        stmt = (
            select(
                OrderItem.item_skuid.label("sku"),
                OrderItem.item_name.label("item_name"),
                OrderItem.quantity.label("quantity"),
                OrderItem.price.label("price"),
                Order.id.label("order_id"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.store_id == self.store_id,
                Order.payment_status == PaymentStatus.COMPLETED,
                *time_filters,
            )
        )
        rows = (await self.db.execute(stmt)).all()
        
        # 3. Fetch Catalog JSON for category mapping
        catalog_service = CatalogService(self.redis, None, self.store_id)
        try:
            catalog = await catalog_service.get_catalog(channel="default", db=self.db)
        except Exception as e:
            logger.error(f"Failed to fetch catalog: {e}", exc_info=True)
            catalog = {"categories": [], "items": []}
            
        # 4. Build mapping tables
        sku_to_cat = {item["skuCode"]: item["categoryId"] for item in catalog.get("items", []) if "skuCode" in item and "categoryId" in item}
        cat_to_name = {cat["categoryId"]: cat["name"] for cat in catalog.get("categories", []) if "categoryId" in cat and "name" in cat}
        
        # 5. In-Memory Aggregation
        # { category_id: { "name": ..., "order_ids": set(), "items": { sku: { ... } } } }
        agg = {}
        for r in rows:
            sku = r.sku
            item_name = r.item_name
            qty = int(r.quantity or 0)
            rev = float((r.price or 0) * qty)
            order_id = r.order_id
            
            cat_id = sku_to_cat.get(sku, "uncategorized")
            cat_name = cat_to_name.get(cat_id, "Uncategorized")
            
            if cat_id not in agg:
                agg[cat_id] = {
                    "name": cat_name,
                    "order_ids": set(),
                    "items": {}
                }
            
            agg[cat_id]["order_ids"].add(order_id)
            
            if sku not in agg[cat_id]["items"]:
                agg[cat_id]["items"][sku] = {
                    "sku": sku,
                    "item_name": item_name,
                    "total_quantity": 0,
                    "total_revenue": 0.0,
                    "order_ids": set()
                }
            
            agg[cat_id]["items"][sku]["total_quantity"] += qty
            agg[cat_id]["items"][sku]["total_revenue"] += rev
            agg[cat_id]["items"][sku]["order_ids"].add(order_id)
            
        # 6. Build response objects and sort
        categories_response = []
        for cat_id, cat_data in agg.items():
            items_list = []
            cat_qty = 0
            cat_rev = 0.0
            
            for sku, item_data in cat_data["items"].items():
                cat_qty += item_data["total_quantity"]
                cat_rev += item_data["total_revenue"]
                items_list.append(CategoryItemEntry(
                    sku=sku,
                    item_name=item_data["item_name"],
                    total_quantity=item_data["total_quantity"],
                    total_revenue=round(item_data["total_revenue"], 2),
                    order_count=len(item_data["order_ids"])
                ))
            
            # Sort items by quantity sold descending
            items_list.sort(key=lambda x: x.total_quantity, reverse=True)
            
            categories_response.append(CategorySummaryEntry(
                category_id=cat_id,
                category_name=cat_data["name"],
                total_quantity=cat_qty,
                total_revenue=round(cat_rev, 2),
                order_count=len(cat_data["order_ids"]),
                items=items_list
            ))
            
        # Sort categories by total quantity sold descending
        categories_response.sort(key=lambda x: x.total_quantity, reverse=True)
        
        return CategorySummaryResponse(
            period=period,
            from_date=from_date,
            to_date=to_date,
            categories=categories_response
        )

