import json
import logging
import redis.asyncio as redis
from typing import Dict, Any, List
from app.utils.petpooja import PetpoojaClient

logger = logging.getLogger(__name__)

class CatalogService:
    def __init__(self, redis_client: redis.Redis, petpooja_client: PetpoojaClient):
        self.redis = redis_client
        self.petpooja = petpooja_client

    async def get_catalog(self, channel: str, db: Any = None) -> Dict[str, Any]:
        """
        Fetches catalog from Petpooja and maps it to the internal format.
        'channel' argument is kept for compatibility but might not be used if Petpooja doesn't support it directly.
        """
        cache_key = f"petpooja_catalog_data_{channel}"

        # 1. Check cache first
        try:
            if cached_data := await self.redis.get(cache_key):
                logger.info(f"Using cached catalog for channel '{channel}'.")
                return json.loads(cached_data)
        except Exception as e:
            logger.error(f"Cache read error for channel '{channel}': {e}", exc_info=True)

        # 2. If not in cache, check Database (Petpooja Push Menu)
        if db:
            from app.db.models.menu import Menu
            from sqlalchemy import select

            logger.info(f"Cache miss. Checking Database for latest pushed menu...")
            try:
                # Assuming 'petpooja' provider and we take the latest
                result = await db.execute(select(Menu).filter(Menu.provider == "petpooja").order_by(Menu.id.desc()).limit(1))
                latest_menu = result.scalar_one_or_none()

                if latest_menu and latest_menu.data:
                    logger.info("Found menu in Database. Processing and caching...")
                    # We reuse process_and_cache_menu but since it also maps, we can just use it or call map directly.
                    # process_and_cache_menu also updates Redis, which is good.
                    return await self.process_and_cache_menu(latest_menu.data, channel)
            except Exception as e:
                logger.error(f"Database read error: {e}", exc_info=True)

        # 3. If not in DB or DB failed, fetch from Petpooja API (Legacy/Fallback)
        # Note: This might be deprecated, but kept as final fallback.
        logger.info(f"Cache/DB miss. Fetching fresh catalog from Petpooja API...")
        pp_response = await self.petpooja.fetch_menu()

        catalog_data = self._map_petpooja_response(pp_response)

        # TODO: Update these IDs with actual Petpooja Category IDs from the fetched menu
        CATEGORY_IMAGES = {

        }

        if catalog_data and "categories" in catalog_data:
            # 1. Inject Images
            for category in catalog_data["categories"]:
                cat_id = str(category.get("categoryId"))
                if cat_id in CATEGORY_IMAGES:
                    category["imageURL"] = CATEGORY_IMAGES[cat_id]
                # Default placeholder if from Petpooja response (if they ever add it)
                elif category.get("category_image_url"):
                     category["imageURL"] = category.get("category_image_url")


            # 2. Sort Categories (Logic kept, but requires valid IDs to work)
            # For now, we sort by 'categoryrank' if available from Petpooja
            def get_sort_index(cat):
                rank = cat.get("categoryrank")
                return int(rank) if rank is not None else 999

            catalog_data["categories"].sort(key=get_sort_index)

        # 3. Store in cache
        try:
            await self.redis.set(cache_key, json.dumps(catalog_data), ex=3600)
            logger.info(f"Successfully cached catalog for channel '{channel}'.")
        except Exception as e:
            logger.warning(f"Cache write error for channel '{channel}': {e}", exc_info=True)

        return catalog_data

    async def process_and_cache_menu(self, menu_data: Dict[str, Any], channel: str = "default") -> Dict[str, Any]:
        """
        Process the raw menu data from Petpooja and cache the result.
        This is called by the webhook.
        """
        logger.info(f"Processing and caching menu update for channel '{channel}'")

        # Map raw data to internal format
        catalog_data = self._map_petpooja_response(menu_data)

        # Inject Images & Sort (Reuse logic - TODO: Refactor common logic)
        CATEGORY_IMAGES = {
            "6868ca5dc29c8ed4d3c98dd5": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032823/Idli_oh6wpb.jpg",
            "68e778dd0c42e107fdf5cf3f": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767786181/360_F_786760607_IwcScz3k7Efj42i1S7mnewhWQXrhAa0o_dnjnqq.jpg",
            "6868ca5dc29c8ed4d3c98dd4": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032824/Davanagere_Dose_rsju7o.jpg",
            "6868ca5dc29c8ed4d3c98dd8": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032824/Coffee_f8hx0m.jpg",
            "6868ca5dc29c8ed4d3c98dd3": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032828/Bengaluru_Dose_bdrozv.jpg",
            "6868ca5dc29c8ed4d3c98dd7": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032825/Rice_j5hjnu.jpg",
            "6868ca5dc29c8ed4d3c98dd6": "https://res.cloudinary.com/dr01mnmi7/image/upload/v1767032827/WadaSnacks_nkhdsn.jpg"
        }

        if catalog_data and "categories" in catalog_data:
            for category in catalog_data["categories"]:
                cat_id = str(category.get("categoryId"))
                if cat_id in CATEGORY_IMAGES:
                    category["imageURL"] = CATEGORY_IMAGES[cat_id]
                elif category.get("category_image_url"):
                     category["imageURL"] = category.get("category_image_url")

            def get_sort_index(cat):
                rank = cat.get("categoryrank")
                return int(rank) if rank is not None else 999
            catalog_data["categories"].sort(key=get_sort_index)

        # Cache
        cache_key = f"petpooja_catalog_data_{channel}"
        try:
            # Set with long expiry (e.g. 24 hours) as we rely on webhook pushes now
            await self.redis.set(cache_key, json.dumps(catalog_data), ex=86400)
            logger.info(f"Updated cache for channel '{channel}' via webhook.")
        except Exception as e:
            logger.error(f"Failed to update cache for channel '{channel}': {e}", exc_info=True)

        return catalog_data

    def _map_petpooja_response(self, pp_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Maps Petpooja 'Fetch Menu' JSON to Internal Catalog Format.
        Matches the legacy 'Rista' structure for frontend compatibility.
        """

        # Constants for Tag IDs (Legacy IDs preserved for consistency)
        TAG_VEG_ID = "6868c0ab6065bace3cd952b7"
        TAG_NON_VEG_ID = "6868c0ab6065bace3cd952b8"
        TAG_EGG_ID = "6868c0ab6065bace3cd952bb"

        # Define available Item Tags
        item_tags = [
            {"itemTagId": TAG_VEG_ID, "name": "Vegetarian"},
            {"itemTagId": TAG_NON_VEG_ID, "name": "Non-vegetarian"},
            {"itemTagId": TAG_EGG_ID, "name": "Egg"},
            # Add others if needed, but these are the core ones derived from attributes
        ]

        mapped = {
            "categories": [],
            "schedules": [],
            "itemTags": item_tags,
            "charges": [], # Empty for now, Petpooja handles charges at order level usually
            "items": [],
            "optionSets": [],
            "discounts": [],
            "memberships": [],
            "taxTypes": []
        }

        # 1. Map Taxes
        for tx in pp_data.get("taxes", []):
            mapped["taxTypes"].append({
                "taxTypeId": str(tx.get("taxid")),
                "name": tx.get("taxname"),
                "percentage": float(tx.get("tax", 0.0)),
                "type": tx.get("taxtype")
            })

        # 2. Map Categories
        for cat in pp_data.get("categories", []):
            mapped["categories"].append({
                "categoryId": str(cat.get("categoryid")),
                "name": cat.get("categoryname"),
                "subCategories": [], # Legacy field
                "imageURL": cat.get("category_image_url", ""),
                "categoryrank": cat.get("categoryrank"),
                "active": cat.get("active")
            })

        # 3. Map Items (and Variations)
        for item in pp_data.get("items", []):
            if str(item.get("active")) != "1":
                continue

            tax_ids = item.get("item_tax", "").split(",") if item.get("item_tax") else []
            tax_ids = [t.strip() for t in tax_ids if t.strip()]

            # Determine Tag IDs based on attribute
            # 1 = Veg, 2 = Non-Veg, 3 = Egg (Common convention, adjusting as needed)
            attr_id = str(item.get("item_attributeid"))
            current_tag_ids = []
            if attr_id == "1":
                current_tag_ids.append(TAG_VEG_ID)
            elif attr_id == "2":
                current_tag_ids.append(TAG_NON_VEG_ID)
            elif attr_id == "3":
                current_tag_ids.append(TAG_EGG_ID)

            # Base Item
            mapped_item = {
                "itemId": str(item.get("itemid")),
                "skuCode": str(item.get("itemid")),
                "itemName": item.get("itemname"),
                "price": float(item.get("price", 0.0)),
                "taxTypeIds": tax_ids,
                "categoryId": str(item.get("item_categoryid")),
                "isPriceIncludesTax": False, # Petpooja usually sends exclusive prices
                "status": "Active",
                "description": item.get("itemdescription", ""),
                "type": "Simple", # Legacy "type" seems to be "Simple" for items, not Veg/NonVeg
                "itemTagIds": current_tag_ids,
                "chargeIds": [],
                "scheduleIds": [],
                "measuringUnit": "ea",
                "itemNature": "Service",
                "denyDiscount": False,
                "imageURL": item.get("item_image_url", ""),
                "optionSetIds": []
            }

            # Check for Variations
            variations = item.get("variation", [])
            if not variations:
                # No variations, add base item
                mapped["items"].append(mapped_item)
            else:
                # Flatten variations
                for var in variations:
                    if str(var.get("active")) != "1":
                        continue

                    var_item = mapped_item.copy()
                    var_item["itemId"] = str(var.get("id"))
                    var_item["skuCode"] = str(var.get("id"))
                    var_item["itemName"] = f"{item.get('itemname')} ({var.get('name')})"
                    var_item["price"] = float(var.get("price", 0.0))
                    # Inherit taxes and tags from parent
                    mapped["items"].append(var_item)

        return mapped

    # --- KDS Helper Methods ---

    def money(self, x: float) -> float:
        from decimal import Decimal, ROUND_HALF_UP
        return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def find_item(self, catalog_items: list, sku: str | None = None) -> Dict | None:
        for it in catalog_items:
            # Check status logic? Already filtered active in map, but keep safe
            if it.get("status") != "Active":
                continue
            if sku is not None and str(it.get("skuCode")) == str(sku):
                return it
        return None

    def calculate_tax_amounts(self, sale_amount: float, tax_percentage: float, price_includes_tax: bool) -> tuple[float, float]:
        if price_includes_tax:
            tax_amount = (sale_amount * tax_percentage) / (100 + tax_percentage)
            return self.money(tax_amount), 0.0
        else:
            tax_amount = (sale_amount * tax_percentage) / 100
            return 0.0, self.money(tax_amount)

    def build_sale_item(self, src_item: Dict, qty: int, tax_index: Dict) -> tuple[Dict, float, float]:
        qty = int(qty)
        unit_price = float(src_item["price"])
        item_amount = unit_price * qty

        taxes = []
        total_tax_included = 0.0
        total_tax_excluded = 0.0
        price_includes_tax = bool(src_item.get("isPriceIncludesTax", False))

        for tax_id in src_item.get("taxTypeIds", []):
            meta = tax_index.get(tax_id)
            if not meta:
                continue

            rate = float(meta["percentage"])
            amount_included, amount_excluded = self.calculate_tax_amounts(
                item_amount, rate, price_includes_tax
            )

            total_tax_included += amount_included
            total_tax_excluded += amount_excluded

            taxes.append({
                "id": str(tax_id),
                "name": meta["name"],
                "percentage": rate,
                "saleAmount": self.money(item_amount),
                "amountIncluded": amount_included,
                "amountExcluded": amount_excluded,
                "amount": self.money(amount_included + amount_excluded),
            })

        item_total_amount = self.money(item_amount)
        # For legacy compatibility with KDS structure, we keep this,
        # though build_sale_item typically preps for the syncing payload.
        line = {
            "shortName": src_item["itemName"],
            "skuCode": src_item["skuCode"],
            "quantity": qty,
            "unitPrice": self.money(unit_price),
            "itemAmount": item_total_amount,
            "itemNature": "Service",
            "itemTotalAmount": item_total_amount,
        }

        if taxes:
            if total_tax_included: line["taxAmountIncluded"] = self.money(total_tax_included)
            if total_tax_excluded: line["taxAmountExcluded"] = self.money(total_tax_excluded)
            line["taxes"] = taxes

        return line, total_tax_included, total_tax_excluded

    def summarize_taxes(self, items: list) -> list:
        agg = {}
        for it in items:
            for t in it.get("taxes", []):
                key = (t["name"], t["percentage"])
                entry = agg.setdefault(key, {
                    "name": t["name"],
                    "percentage": t["percentage"],
                    "saleAmount": 0.0,
                    "itemTaxIncluded": 0.0,
                    "itemTaxExcluded": 0.0,
                    "chargeTaxIncluded": 0.0,
                    "chargeTaxExcluded": 0.0,
                    "amountIncluded": 0.0,
                    "amountExcluded": 0.0,
                    "amount": 0.0,
                })
                entry["saleAmount"] += float(t.get("saleAmount", 0.0))
                inc = float(t.get("amountIncluded", 0.0))
                exc = float(t.get("amountExcluded", 0.0))
                entry["itemTaxIncluded"] += inc
                entry["itemTaxExcluded"] += exc
                entry["amountIncluded"] += inc
                entry["amountExcluded"] += exc
                entry["amount"] += float(t.get("amount", 0.0))

        for v in agg.values():
            for k in ["saleAmount", "itemTaxIncluded", "itemTaxExcluded",
                      "chargeTaxIncluded", "chargeTaxExcluded",
                      "amountIncluded", "amountExcluded", "amount"]:
                v[k] = self.money(v[k])
        return list(agg.values())
