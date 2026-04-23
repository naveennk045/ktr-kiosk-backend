import logging
import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_catalog_service, get_redis_client, get_db, get_store_context
from app.db.models.store import Store
from app.services.catalog_service import CatalogService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def get_catalog(
    channel: str,
    service: CatalogService = Depends(get_catalog_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Get catalog for a specific channel.
    """
    return await service.get_catalog(channel, db)


@router.delete("/cache")
async def clear_catalog_cache(
    channel: str,
    store: Store = Depends(get_store_context),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Manually clear catalog cache for a specific channel.
    """
    cache_key = f"petpooja_catalog_data_{store.id}_{channel}"
    deleted = await redis_client.delete(cache_key)

    if deleted > 0:
        logger.info(f"Catalog cache cleared for channel '{channel}' (store {store.id})")
        return {
            "status": "success",
            "message": f"Cache cleared for channel '{channel}'",
            "deleted": True,
        }
    logger.info(f"No cache found for channel '{channel}' (store {store.id})")
    return {
        "status": "success",
        "message": f"No cache found for channel '{channel}'",
        "deleted": False,
    }


@router.get("/cache-stats")
async def get_cache_stats(
    store: Store = Depends(get_store_context),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Get statistics about cached catalogs for this store.
    """
    try:
        pattern = f"petpooja_catalog_data_{store.id}_*"
        keys = await redis_client.keys(pattern)
        suffixes = [k.replace(f"petpooja_catalog_data_{store.id}_", "") for k in keys]

        return {
            "status": "success",
            "store_id": str(store.id),
            "total_cached_channels": len(suffixes),
            "channels": suffixes,
            "cache_status": "healthy" if keys else "empty",
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            "status": "error",
            "message": str(e),
            "cached_channels": 0,
        }
