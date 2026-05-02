import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

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
        description="IST window: today, yesterday, last 7 days (from 00:00), or all completed orders.",
    ),
    service: DashboardService = Depends(get_dashboard_service),
):
    return await service.get_analytics_summary(period)


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
    status: Optional[str] = None,
    search: Optional[str] = None,
    service: DashboardService = Depends(get_dashboard_service),
):
    return await service.get_orders_grid(
        page, size, sortBy, sortDir, period, status, search
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
        description="IST window: today, yesterday, last_week, or all_time.",
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
    return await service.get_top_items(period, limit)


@analytics_router.get("/items/daily", response_model=ItemDailyResponse)
async def get_daily_item_counts(
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, or all_time.",
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
    return await service.get_daily_item_counts(period, sku)


@analytics_router.get("/items/summary", response_model=ItemSummaryResponse)
async def get_item_summary(
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, or all_time.",
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
    return await service.get_item_summary(period)
