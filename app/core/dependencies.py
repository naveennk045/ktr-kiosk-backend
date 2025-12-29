from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import redis.asyncio as redis

from app.db.session import get_db
from app.utils.rista import RistaClient
from app.services.catalog_service import CatalogService
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService

async def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client

async def get_redis_client(request: Request) -> redis.Redis:
    if request.app.state.redis_client is None:
        raise HTTPException(status_code=503, detail="Redis connection not available")
    return request.app.state.redis_client

async def get_rista_client(http_client = Depends(get_http_client)) -> RistaClient:
    return RistaClient(http_client)

async def get_catalog_service(
        redis_client = Depends(get_redis_client),
        rista_client = Depends(get_rista_client)
) -> CatalogService:
    return CatalogService(redis_client, rista_client)

async def get_order_service(
        db = Depends(get_db),
        catalog_service = Depends(get_catalog_service),
        rista_client = Depends(get_rista_client)
) -> OrderService:
    return OrderService(db, catalog_service, rista_client)

async def get_payment_service(
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client),
        order_service: OrderService = Depends(get_order_service),
) -> PaymentService:
    return PaymentService(db, http_client, redis_client, order_service)
