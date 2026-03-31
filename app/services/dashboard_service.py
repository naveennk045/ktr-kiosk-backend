import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, asc, case
from app.db.models.order import Order, PaymentStatus, OrderType, PaymentMethod
from app.db.schemas.dashboard import (
    AnalyticsSummaryResponse,
    DashboardPeriod,
    OrderGridResponse,
    OrderGridItem,
    OrderDetailResponse,
)
from typing import Optional

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _time_filters_for_period(period: DashboardPeriod) -> list:
    """IST calendar boundaries. last_week = from 00:00 seven days ago through now."""
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
    raise ValueError(f"Unknown period: {period}")


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_analytics_summary(self, period: DashboardPeriod) -> AnalyticsSummaryResponse:
        time_filters = _time_filters_for_period(period)
        base = [Order.payment_status == PaymentStatus.COMPLETED, *time_filters]

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
    ) -> OrderGridResponse:

        # Base Query
        stmt = select(Order)

        for cond in _time_filters_for_period(period):
            stmt = stmt.where(cond)

        # Filtering
        if status:
            stmt = stmt.where(Order.payment_status == status)

        if search:
            stmt = stmt.where(Order.order_id.ilike(f"%{search}%"))

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
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()

        if not order:
            return None

        # Build detailed response
        return OrderDetailResponse(
            orderRefId=order.order_id,
            location=order.channel,
            amount=float(order.total_amount_include_tax),
            paymentStatus=order.payment_status,
            erpStatus=order.kds_status,
            items=order.items,
            paymentMeta=order.provider_resp,
            createdAt=order.created_at
        )

