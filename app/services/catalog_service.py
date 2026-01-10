import json
import logging
import redis.asyncio as redis
from typing import Dict, Any
from app.utils.rista import RistaClient

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

        # Inject static category images
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
            # 1. Inject Images
            for category in catalog_data["categories"]:
                cat_id = category.get("categoryId")
                if cat_id in CATEGORY_IMAGES:
                    category["imageURL"] = CATEGORY_IMAGES[cat_id]

            # 2. Sort Categories
            CATEGORY_ORDER = [
                "6868ca5dc29c8ed4d3c98dd3",  # Davanagere Dose
                "6868ca5dc29c8ed4d3c98dd4",  # Bengaluru Dose
                "6868ca5dc29c8ed4d3c98dd5",  # Idli
                "6868ca5dc29c8ed4d3c98dd7",  # Rice
                "6868ca5dc29c8ed4d3c98dd6",  # Wada/Snacks
                "6868ca5dc29c8ed4d3c98dd8",  # Coffee
                "68e778dd0c42e107fdf5cf3f",  # BEVERAGE
            ]

            def get_sort_index(cat):
                cid = cat.get("categoryId")
                try:
                    return CATEGORY_ORDER.index(cid)
                except ValueError:
                    return 999  # Put unknown categories at the end

            catalog_data["categories"].sort(key=get_sort_index)

        # 3. Store in cache
        try:
            await self.redis.set(cache_key, json.dumps(catalog_data), ex=3600)
            logger.info(f"Successfully cached catalog for channel '{channel}'.")
        except Exception as e:
            logger.warning(f"Cache write error for channel '{channel}': {e}", exc_info=True)

        return catalog_data

    # --- KDS Helper Methods (Moved from rista_utils) ---

    def money(self, x: float) -> float:
        from decimal import Decimal, ROUND_HALF_UP
        return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def find_item(self, catalog_items: list, sku: str | None = None) -> Dict | None:
        for it in catalog_items:
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
                "name": meta["name"],
                "percentage": rate,
                "saleAmount": self.money(item_amount),
                "amountIncluded": amount_included,
                "amountExcluded": amount_excluded,
                "amount": self.money(amount_included + amount_excluded),
            })

        item_total_amount = self.money(item_amount)
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
