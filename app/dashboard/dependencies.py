import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.dependencies import get_store_context, get_redis_client
from app.db.models.store import Store
from app.db.session import get_db
from app.dashboard.service import DashboardService


async def get_dashboard_service(
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
    store: Store = Depends(get_store_context),
) -> DashboardService:
    return DashboardService(db, store.id, redis_client)

