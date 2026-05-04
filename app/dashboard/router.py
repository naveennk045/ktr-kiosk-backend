import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from app.db.models.order import OrderType, PaymentStatus, PaymentMethod, KdsStatus

from app.dashboard.dependencies import get_dashboard_service
from app.dashboard.schemas import (
    AnalyticsSummaryResponse,
    DashboardPeriod,
    OrderDetailResponse,
    OrderGridResponse,
    ItemTopResponse,
    ItemDailyResponse,
    ItemSummaryResponse,
)
from app.dashboard.service import DashboardService

logger = logging.getLogger(__name__)

analytics_router = APIRouter()

orders_read_router = APIRouter()


@analytics_router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    period: DashboardPeriod = Query(
        "all_time",
        description="IST window: today, yesterday, last_7_days, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    service: DashboardService = Depends(get_dashboard_service),
):
    return await service.get_analytics_summary(period, from_date, to_date)


@orders_read_router.get("/", response_model=OrderGridResponse)
async def get_orders(
    page: int = 0,
    size: int = 20,
    sortBy: str = "created_at",
    sortDir: str = "desc",
    period: DashboardPeriod = Query(
        "all_time",
        description="Same IST windows as /analytics/summary.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    status: Optional[str] = None,
    search: Optional[str] = None,
    start_at: datetime | None = Query(None, description="Optional UTC/ISO start datetime"),
    end_at: datetime | None = Query(None, description="Optional UTC/ISO end datetime"),
    order_type: OrderType | None = Query(None),
    payment_status: PaymentStatus | None = Query(None),
    payment_method: PaymentMethod | None = Query(None),
    kds_status: KdsStatus | None = Query(None),
    channel: str | None = Query(None),
    terminal_id: str | None = Query(None),
    min_amount: float | None = Query(None, ge=0),
    max_amount: float | None = Query(None, ge=0),
    service: DashboardService = Depends(get_dashboard_service),
):
    return await service.get_orders_grid(
        page, size, sortBy, sortDir, period, status, search, from_date, to_date,
        start_at, end_at, order_type, payment_status, payment_method, kds_status,
        channel, terminal_id, min_amount, max_amount
    )


@orders_read_router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order_detail(
    order_id: str,
    service: DashboardService = Depends(get_dashboard_service),
):
    order = await service.get_order_detail(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


# ─── Item-wise Analytics Endpoints ───────────────────────────────────────────────

@analytics_router.get("/items/top", response_model=ItemTopResponse)
async def get_top_items(
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Number of top items to return (max 100).",
    ),
    service: DashboardService = Depends(get_dashboard_service),
):
    """
    **Top N items** ranked by total quantity sold in the given period.

    Returns each item's SKU, name, total quantity sold, total revenue generated,
    and the number of orders that contained it.
    """
    return await service.get_top_items(period, limit, from_date, to_date)


@analytics_router.get("/items/daily", response_model=ItemDailyResponse)
async def get_daily_item_counts(
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    sku: Optional[str] = Query(
        None,
        description="Filter results to a single item SKU. Leave blank for all items.",
    ),
    service: DashboardService = Depends(get_dashboard_service),
):
    """
    **Daily item order counts** — how many of each item was ordered each day.

    Each row contains: date (IST), sku, item_name, total_quantity, order_count.
    Optionally pass `sku` to drill into a specific item's daily trend.
    """
    return await service.get_daily_item_counts(period, sku, from_date, to_date)


@analytics_router.get("/items/summary", response_model=ItemSummaryResponse)
async def get_item_summary(
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Used when period=custom_range. Format: YYYY-MM-DD.",
    ),
    service: DashboardService = Depends(get_dashboard_service),
):
    """
    **Full item-wise summary** for the period.

    Returns all items sorted by popularity with:
    - `total_quantity` — sum of units sold
    - `total_revenue` — revenue contribution (price × qty)
    - `order_count` — distinct orders containing the item
    - `avg_quantity_per_order` — average units per order

    Also returns aggregate `total_items_sold` and `unique_items` at the top level.
    """
    return await service.get_item_summary(period, from_date, to_date)
