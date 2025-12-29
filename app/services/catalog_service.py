import json
import logging
import redis.asyncio as redis
from typing import Dict, Any
from app.integrations.rista_client import RistaClient

logger = logging.getLogger(__name__)

class CatalogService:
    def __init__(self, redis_client: redis.Redis, rista_client: RistaClient):
        self.redis = redis_client
        self.rista = rista_client

    async def get_catalog(self, channel: str) -> Dict[str, Any]:
        cache_key = f"{channel}_catalog_data"

        # 1. Check cache first
        try:
            if cached_data := await self.redis.get(cache_key):
                logger.info(f"Using cached catalog for channel '{channel}'.")
                return json.loads(cached_data)
        except Exception as e:
            logger.error(f"Cache read error for channel '{channel}': {e}", exc_info=True)

        # 2. If not in cache, fetch from Rista
        logger.info(f"Cache miss. Fetching fresh catalog for channel '{channel}' from Rista...")
        catalog_data = await self.rista.fetch_catalog_raw(channel)

        # 3. Store in cache
        try:
            await self.redis.set(cache_key, json.dumps(catalog_data), ex=3600)
            logger.info(f"Successfully cached catalog for channel '{channel}'.")
        except Exception as e:
            logger.warning(f"Cache write error for channel '{channel}': {e}", exc_info=True)

        return catalog_data