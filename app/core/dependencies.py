from fastapi import Request, HTTPException
import httpx
import redis.asyncio as redis


async def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    Returns the shared httpx.AsyncClient.
    """
    return request.app.state.http_client


async def get_redis_client(request: Request) -> redis.Redis:
    """
    Returns the shared redis.Redis client.
    Raises an error if Redis is not available.
    """
    if request.app.state.redis_client is None:
        raise HTTPException(
            status_code=503,
            detail="Redis connection not available"
        )
    return request.app.state.redis_client
