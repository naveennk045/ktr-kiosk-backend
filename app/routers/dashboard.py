from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.dashboard_service import DashboardService
from app.db.schemas.dashboard import AnalyticsSummaryResponse, DashboardPeriod

router = APIRouter()

async def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)

@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    period: DashboardPeriod = Query(
        "all_time",
        description="IST window: today, yesterday, last 7 days (from 00:00), or all completed orders.",
    ),
    service: DashboardService = Depends(get_dashboard_service),
):
    return await service.get_analytics_summary(period)
