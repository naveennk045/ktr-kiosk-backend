
import logging
from fastapi import APIRouter, Depends

import httpx
import redis.asyncio as redis

from app.core.dependencies import get_http_client, get_redis_client
from app.core.rista_utils import get_catalog_data

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def get_catalog(
        channel: str,
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Get catalog for a specific channel.
    
    This endpoint delegates to get_catalog_data() utility function,
    which handles caching and Rista API calls as single source of truth.
    
    Args:
        channel: Channel name (e.g., "Palas Kiosk", "QSR Hub")
        
    Returns:
        dict: Catalog data with categories, items, taxes, charges
        
    Raises:
        HTTPException: If catalog fetch fails or Redis is unavailable
    """
    return await get_catalog_data(channel, redis_client, http_client)


@router.delete("/cache")
async def clear_catalog_cache(
        channel: str,
        redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Manually clear catalog cache for a specific channel.
    
    Useful when:
    - Rista catalog is updated and needs immediate refresh
    - Cache appears corrupted
    - Testing cache behavior
    
    Args:
        channel: Channel name to clear cache for
        
    Returns:
        dict: Status message and whether cache was deleted
    """
    cache_key = f"{channel}_catalog_data"
    deleted = await redis_client.delete(cache_key)

    if deleted > 0:
        logger.info(f"Catalog cache cleared for channel '{channel}'")
        return {
            "status": "success",
            "message": f"Cache cleared for channel '{channel}'",
            "deleted": True
        }
    else:
        logger.info(f"No cache found for channel '{channel}'")
        return {
            "status": "success",
            "message": f"No cache found for channel '{channel}'",
            "deleted": False
        }


@router.get("/cache-stats")
async def get_cache_stats(
        redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Get statistics about cached catalogs.
    
    Useful for monitoring which channels have cached catalogs
    and overall cache health.
    
    Returns:
        dict: List of cached channels and count
    """
    try:
        # Find all catalog cache keys
        keys = await redis_client.keys("*_catalog_data")

        cached_channels = [k.replace("_catalog_data", "") for k in keys]

        return {
            "status": "success",
            "total_cached_channels": len(cached_channels),
            "channels": cached_channels,
            "cache_status": "healthy" if keys else "empty"
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            "status": "error",
            "message": str(e),
            "cached_channels": 0
        }