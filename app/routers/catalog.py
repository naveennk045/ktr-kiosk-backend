import logging
import redis.asyncio as redis
from fastapi import APIRouter, Depends
from app.core.dependencies import get_catalog_service, get_redis_client
from app.services.catalog_service import CatalogService

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/")
async def get_catalog(
        channel: str,
        service: CatalogService = Depends(get_catalog_service)
):
    """
    Get catalog for a specific channel.
    """
    return await service.get_catalog(channel)

@router.delete("/cache")
async def clear_catalog_cache(
        channel: str,
        redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Manually clear catalog cache for a specific channel.
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
    """
    try:
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