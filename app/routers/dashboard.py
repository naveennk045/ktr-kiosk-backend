from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.dashboard_service import DashboardService
from app.db.schemas.dashboard import AnalyticsSummaryResponse

router = APIRouter()

async def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)

@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    service: DashboardService = Depends(get_dashboard_service)
):
    return await service.get_analytics_summary()
