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
    "9534536": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032823/Idli_oh6wpb.jpg",
    "9534539": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032827/WadaSnacks_nkhdsn.jpg",
    "9534538": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774715789/BangaloreDoseCategory_1_wdaz9m.jpg",
    "9534540": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708821/Hotfiltercoffee_suxszm.jpg",
    "9534541": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032825/Rice_j5hjnu.jpg",
    "9593393": "",
    "9593400": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774711037/Gemini_Generated_Image_v6u8odv6u8odv6u8_smbylt.png",
}

# ---------------------------------------------------------------------------
# Item image overrides — keyed by Petpooja itemid (string)
# Update these when item images are added or changed.
# ---------------------------------------------------------------------------
ITEM_IMAGES: Dict[str, str] = {
    # Idli
    "1301947626": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708818/Idlivada_n6brxr.jpg",           # Idli Wada
    "1301947627": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774714101/bengaluru-benne-idli-banashankari-3rd-stage-bangalore-south-indian-restaurants-js26nx1tfc_xp17lb.jpg",  # Benne Idli
    "1301947628": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774714101/bengaluru-benne-idli-banashankari-3rd-stage-bangalore-south-indian-restaurants-js26nx1tfc_xp17lb.jpg",  # Benne Thatte Idli
    "1301947629": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708815/GheePudiThateidli_z1biaa.jpg",  # Ghee Pudi Thatte Idli
    "1301947630": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708815/GheePudiThateidli_z1biaa.jpg",  # Ghee Pudi Idli
    "1301947631": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774713915/best-thatte-idli-in-bangalore-breakfast-cafes_xzynez.jpg",  # Thatte Idli
    "1301947632": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708816/IdliChuntey_p4lkub.jpg",         # Idli Chutney
    # Wada / Snacks
    "1301947645": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708820/DalVada_vtjpgg.jpg",             # Dal Vada
    "1301947646": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032827/WadaSnacks_nkhdsn.jpg",          # Medu Wada
    # Bengaluru Dose
    "1301947637": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708815/BenneMasalaDose_mwszev.jpg",     # Benne Pudi Masala Dose
    "1301947638": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708815/BennePlain_ozxumk.jpg",          # Benne Pudi Plain Dose
    "1301947639": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774715789/BangaloreDoseCategory_1_wdaz9m.jpg",      # Bengaluru Benne Masala Dose
    "1301947640": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708815/BennePlain_ozxumk.jpg",          # Benne Plain Dose
    "1301947641": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708814/Gheemasala_Dose_fctuf0.jpg",    # Ghee Pudi Masala Dose
    "1301947642": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708820/GheePudiPlain_lttc5n.jpg",      # Ghee Pudi Plain Dose
    "1301947643": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708814/Gheemasala_Dose_fctuf0.jpg",    # Ghee Masala Dose
    "1301947644": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708816/GheePlain_hi8966.jpg",           # Ghee Plain Dose
    # Coffee
    "1301947647": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032824/Coffee_f8hx0m.jpg",              # Cold Filter Coffee
    "1301947648": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708821/Hotfiltercoffee_suxszm.jpg",              # Hot Filter Coffee
    # Rice
    "1301947649": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774714290/chow-chow-bhaat-recipe-2_cokysu.jpg",  # Chow Chow Bath
    "1301947655": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774714374/khara-bath-recipe-a_zqsusx.jpg",      # Khara Bath
    "1301947656": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774708822/KesriBath_ekrtwc.jpg",                # Kesari Bath
    # Extras
    "1303112180": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767498181/65afb1fd-9f84-4ae0-b4ea-ad1f78f11835.jpg",  # Packaged Water 1L
    "1303001035": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767498181/65afb1fd-9f84-4ae0-b4ea-ad1f78f11835.jpg",  # Packaged Water 500ml
    # Merchandise (all use shared merchandise image)
    "1302832751": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774712192/DiaryBig_x8sya7.jpg",  # Postcards
   "1302832746": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774710724/Gemini_Generated_Image_v6u8odv6u8odv6u8_gmay0p.png",           # Coasters
    "1302832747": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774712192/Fridgemagnets_mp6slj.jpg",       # Fridge Magnets
    "1302832748": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774712195/DiarySmall_uxovym.jpg",            # Diaries
    "1302832749": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774712193/Totebag_pm8fji.jpg",             # Tote Bags
    "1302832750": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774712194/Tshirts_uk4dlg.jpg",             # T-shirts
    "1302832198": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1774712199/Postcards_dqk4vf.jpg",

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
                catalog_data = json.loads(cached)
                if catalog_data:
                    await self._apply_availability_overrides(catalog_data, db)
                return catalog_data
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
                    catalog_data = await self.process_and_cache_menu(latest_menu.data, channel)
                    if catalog_data:
                        await self._apply_availability_overrides(catalog_data, db)
                    return catalog_data
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

            # Filter out items that are marked as unavailable
            original_count = len(catalog_data.get("items", []))
            catalog_data["items"] = [
                item for item in catalog_data.get("items", [])
                if str(item.get("itemId")) not in overrides
            ]
            new_count = len(catalog_data["items"])

            if original_count != new_count:
                logger.info(f"Removed {original_count - new_count} unavailable items from catalog.")

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
        Inject CATEGORY_IMAGES and ITEM_IMAGES overrides, then sort categories
        by categoryrank. Mutates catalog_data in place.
        """
        # --- Category images ---
        categories = catalog_data.get("categories", [])
        for category in categories:
            cat_id = str(category.get("categoryId"))
            if cat_id in CATEGORY_IMAGES:
                category["imageURL"] = CATEGORY_IMAGES[cat_id]
            elif category.get("category_image_url"):
                category["imageURL"] = category["category_image_url"]

        categories.sort(key=lambda c: int(c["categoryrank"]) if c.get("categoryrank") is not None else 999)

        # --- Item images ---
        for item in catalog_data.get("items", []):
            item_id = str(item.get("itemId", ""))
            if item_id in ITEM_IMAGES:
                item["imageURL"] = ITEM_IMAGES[item_id]
            elif item.get("item_image_url"):
                item["imageURL"] = item["item_image_url"]
