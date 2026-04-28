import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dashboard.dependencies import get_dashboard_service
from app.dashboard.schemas import (
    AnalyticsSummaryResponse,
    DashboardPeriod,
    OrderDetailResponse,
    OrderGridResponse,
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
