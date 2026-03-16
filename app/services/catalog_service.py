"""
CatalogService: cache orchestrator for the Petpooja menu catalog.

Fetch priority (3-tier):
  1. Redis cache       — fastest, set on every successful fetch (TTL varies)
  2. PostgreSQL DB     — latest webhook-pushed menu (fallback if cache cold)
  3. Petpooja Live API — final fallback, 3-retry with exponential backoff

Tax math helpers (money, find_item, build_sale_item, etc.) live in app.utils.tax_utils.
Menu-to-catalog mapping lives in app.services.petpooja_mapper.PetpoojaMapper.
"""
import json
import logging
from typing import Any, Dict, Optional

import redis.asyncio as redis

from app.services.petpooja_mapper import PetpoojaMapper
from app.utils.petpooja import PetpoojaClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category image overrides — keyed by Petpooja categoryid (string)
# Update these when new categories are added or image URLs change.
# ---------------------------------------------------------------------------
CATEGORY_IMAGES: Dict[str, str] = {
    "6868ca5dc29c8ed4d3c98dd5": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032823/Idli_oh6wpb.jpg",
    "68e778dd0c42e107fdf5cf3f": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767786181/360_F_786760607_IwcScz3k7Efj42i1S7mnewhWQXrhAa0o_dnjnqq.jpg",
    "6868ca5dc29c8ed4d3c98dd4": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032824/Davanagere_Dose_rsju7o.jpg",
    "6868ca5dc29c8ed4d3c98dd8": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032824/Coffee_f8hx0m.jpg",
    "6868ca5dc29c8ed4d3c98dd3": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032828/Bengaluru_Dose_bdrozv.jpg",
    "6868ca5dc29c8ed4d3c98dd7": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032825/Rice_j5hjnu.jpg",
    "6868ca5dc29c8ed4d3c98dd6": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032827/WadaSnacks_nkhdsn.jpg",
}


class CatalogService:
    def __init__(self, redis_client: redis.Redis, petpooja_client: Optional[PetpoojaClient]):
        self.redis = redis_client
        self.petpooja = petpooja_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_catalog(self, channel: str, db: Any = None) -> Dict[str, Any]:
        """
        Fetch catalog using 3-tier priority:
          1. Redis cache (fast path)
          2. DB — latest webhook-pushed menu (if db session provided)
          3. Petpooja live API (final fallback, needs petpooja_client)

        'channel' scopes the cache key so different channels can have
        independent catalogs if needed in the future.
        """
        cache_key = f"petpooja_catalog_data_{channel}"

        # 1. Redis cache
        try:
            if cached := await self.redis.get(cache_key):
                logger.info(f"Cache hit for channel '{channel}'.")
                return json.loads(cached)
        except Exception as e:
            logger.error(f"Cache read error for '{channel}': {e}", exc_info=True)

        # 2. DB — latest pushed menu
        if db:
            from app.db.models.menu import Menu
            from sqlalchemy import select

            logger.info("Cache miss. Checking DB for latest pushed menu...")
            try:
                result = await db.execute(
                    select(Menu)
                    .filter(Menu.provider == "petpooja")
                    .order_by(Menu.id.desc())
                    .limit(1)
                )
                latest_menu = result.scalar_one_or_none()
                if latest_menu and latest_menu.data:
                    logger.info("Found menu in DB. Processing and caching...")
                    return await self.process_and_cache_menu(latest_menu.data, channel)
            except Exception as e:
                logger.error(f"DB read error: {e}", exc_info=True)

        # 3. Petpooja live API (legacy / final fallback)
        if self.petpooja is None:
            raise RuntimeError(
                "No Petpooja client configured — cannot fetch live menu. "
                "Ensure a DB-pushed menu exists or Redis cache is warm."
            )

        logger.info("Cache/DB miss. Fetching live catalog from Petpooja API...")
        pp_response = await self.petpooja.fetch_menu()
        catalog_data = self._build_catalog(pp_response)

        # Short TTL (1h) for live-fetched data — webhook push will refresh with 24h TTL
        try:
            await self.redis.set(cache_key, json.dumps(catalog_data), ex=3600)
            logger.info(f"Cached live catalog for channel '{channel}' (TTL=1h).")
        except Exception as e:
            logger.warning(f"Cache write error for '{channel}': {e}", exc_info=True)

        if catalog_data:
            await self._apply_availability_overrides(catalog_data, db)

        return catalog_data

    async def _apply_availability_overrides(self, catalog_data: Dict[str, Any], db: Any) -> None:
        """
        Fetch all active overrides from the database and apply them to the catalog.
        Items explicitly marked as is_available=False will be set to status='Inactive'.
        """
        if not db:
            return

        from app.db.models.item_availability import ItemAvailability
        from sqlalchemy import select

        try:
            # We only care about items that are turned OFF
            stmt = select(ItemAvailability).where(ItemAvailability.is_available == False)
            result = await db.execute(stmt)
            overrides = {oa.sku_code for oa in result.scalars().all()}

            if not overrides:
                return

            logger.info(f"Applying {len(overrides)} item availability overrides.")
            
            for item in catalog_data.get("items", []):
                if str(item.get("itemId")) in overrides:
                    item["status"] = "Inactive"
                    
        except Exception as e:
            logger.error(f"Error applying availability overrides: {e}", exc_info=True)

    async def process_and_cache_menu(
        self, menu_data: Dict[str, Any], channel: str = "default"
    ) -> Dict[str, Any]:
        """
        Process raw Petpooja webhook menu data, refresh all channel caches.
        Called by the Petpooja webhook router after storing to DB.
        TTL is 24h since we rely on webhook pushes for updates.
        """
        logger.info(f"Processing and caching webhook menu for channel '{channel}'...")
        catalog_data = self._build_catalog(menu_data)

        # Invalidate all existing channel caches (menu is global across channels)
        try:
            keys = await self.redis.keys("petpooja_catalog_data_*")
            if keys:
                await self.redis.delete(*keys)
                logger.info(f"Cleared {len(keys)} catalog cache key(s).")
        except Exception as e:
            logger.error(f"Error clearing cache keys: {e}", exc_info=True)

        # Write updated cache for this channel
        cache_key = f"petpooja_catalog_data_{channel}"
        try:
            await self.redis.set(cache_key, json.dumps(catalog_data), ex=86400)
            logger.info(f"Cached webhook menu for channel '{channel}' (TTL=24h).")
        except Exception as e:
            logger.error(f"Failed to cache menu for '{channel}': {e}", exc_info=True)

        return catalog_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_catalog(self, pp_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map raw Petpooja data → internal catalog, then apply image overrides + sort."""
        catalog_data = PetpoojaMapper(pp_data).build()
        self._apply_images_and_sort(catalog_data)
        return catalog_data

    @staticmethod
    def _apply_images_and_sort(catalog_data: Dict[str, Any]) -> None:
        """
        Inject CATEGORY_IMAGES overrides and sort categories by categoryrank.
        Mutates catalog_data in place.
        """
        categories = catalog_data.get("categories", [])
        for category in categories:
            cat_id = str(category.get("categoryId"))
            if cat_id in CATEGORY_IMAGES:
                category["imageURL"] = CATEGORY_IMAGES[cat_id]
            elif category.get("category_image_url"):
                category["imageURL"] = category["category_image_url"]

        categories.sort(key=lambda c: int(c["categoryrank"]) if c.get("categoryrank") is not None else 999)
