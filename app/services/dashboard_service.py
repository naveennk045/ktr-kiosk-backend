import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, asc, text
from app.db.models.order import Order, PaymentStatus, KdsStatus
from app.db.schemas.dashboard import (
    AnalyticsSummaryResponse, OrderGridResponse, OrderGridItem, OrderDetailResponse
)
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_analytics_summary(self) -> AnalyticsSummaryResponse:
        # Total Revenue (sum of total_amount_include_tax for COMPLETED payments)
        # Note: Depending on business logic, might filter by date range.
        # Assuming "all time" or "today" based on requirements. User didn't specify, assumes all time or recent?
        # Usually dashboard headers are "Today" or specific. The response example has 42500, lets assume all time for now or standard.

        stmt_revenue = select(func.sum(Order.total_amount_include_tax)).where(
            Order.payment_status == PaymentStatus.COMPLETED
        )
        total_revenue = (await self.db.execute(stmt_revenue)).scalar() or 0.0

        # Total Orders
        stmt_count = select(func.count(Order.id))
        total_orders = (await self.db.execute(stmt_count)).scalar() or 0

        # Pending Payments
        stmt_pending = select(func.count(Order.id)).where(
            Order.payment_status == PaymentStatus.PENDING
        )
        pending_payments = (await self.db.execute(stmt_pending)).scalar() or 0

        # Sync Failures (KDS Status FAILED)
        stmt_failures = select(func.count(Order.id)).where(
            Order.kds_status == KdsStatus.FAILED
        )
        sync_failures = (await self.db.execute(stmt_failures)).scalar() or 0

        return AnalyticsSummaryResponse(
            totalRevenue=total_revenue,
            totalOrders=total_orders,
            pendingPayments=pending_payments,
            syncFailures=sync_failures
        )

    async def get_orders_grid(
        self,
        page: int,
        size: int,
        sort_by: str,
        sort_dir: str,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> OrderGridResponse:

        # Base Query
        stmt = select(Order)

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
            # Items Summary
            item_names = [i.get("name", "Item") for i in (o.items or [])] # simple extract
            summary_text = item_names[0] if item_names else "No Items"
            if len(item_names) > 1:
                summary_text += f" (+{len(item_names)-1} more)"

            content.append(OrderGridItem(
                orderRefId=o.order_id,
                location=o.channel, # Assuming location maps to channel or need separate logic
                amount=float(o.total_amount_include_tax),
                paymentStatus=o.payment_status,
                erpStatus=o.kds_status,
                itemsSummary=summary_text,
                createdAt=o.created_at
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

