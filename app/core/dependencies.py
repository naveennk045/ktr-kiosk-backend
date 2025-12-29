from fastapi import Request, HTTPException, Depends
import httpx
import redis.asyncio as redis
from app.integrations.rista_client import RistaClient
from app.services.catalog_service import CatalogService

async def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client

async def get_redis_client(request: Request) -> redis.Redis:
    if request.app.state.redis_client is None:
        raise HTTPException(
            status_code=503,
            detail="Redis connection not available"
        )
    return request.app.state.redis_client

async def get_rista_client(
        http_client: httpx.AsyncClient = Depends(get_http_client)
) -> RistaClient:
    return RistaClient(http_client)

async def get_catalog_service(
        redis_client: redis.Redis = Depends(get_redis_client),
        rista_client: RistaClient = Depends(get_rista_client)
) -> CatalogService:
    return CatalogService(redis_client, rista_client)