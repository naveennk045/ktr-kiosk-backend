import time
from decimal import Decimal, ROUND_HALF_UP

import jwt
import logging
import httpx
import json
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
import redis.asyncio as redis

from .config import settings

logger = logging.getLogger(__name__)


def generate_jwt_token():
    """
    Using the secret key and api-key we need to generate token.
    """
    token_creation_time = int(time.time())
    payload = {
        "iss": settings.PI_KEY,
        "iat": token_creation_time
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


async def get_catalog_data(
        channel: str,
        redis_client: redis.Redis,
        http_client: httpx.AsyncClient
) -> dict:
    # ... (code from your example) ...
    cache_key = f"{channel}_catalog_data"

    # 1. Check cache first
    try:
        if cached_data := await redis_client.get(cache_key):
            logger.info(f"Using cached catalog for channel '{channel}'.")
            return json.loads(cached_data)
    except Exception as e:
        logger.error(f"Cache read error for channel '{channel}': {e}", exc_info=True)

    # 2. If not in cache, fetch from Rista
    logger.info(f"Cache miss. Fetching fresh catalog for channel '{channel}' from Rista...")
    try:
        token = await run_in_threadpool(generate_jwt_token)
    except Exception as e:
        logger.error(f"Failed to generate JWT: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process authentication."
        )

    headers = {
        "x-api-key": settings.PI_KEY, "x-api-token": token, "content-type": 'application/json'
    }
    params = {"branch": settings.BRANCH_CODE, "channel": channel}

    try:
        url = f"{settings.RISTA_BASE_URL}/catalog"
        response = await http_client.get(url, headers=headers, params=params)
        response.raise_for_status()
        catalog_data = response.json()

        if catalog_data is None:
            raise HTTPException(status_code=502, detail="Upstream API returned null data.")

        # 4. Store in cache
        try:
            await redis_client.set(cache_key, json.dumps(catalog_data), ex=3600)
            logger.info(f"Successfully cached catalog for channel '{channel}'.")
        except Exception as e:
            logger.warning(f"Cache write error for channel '{channel}': {e}", exc_info=True)

        return catalog_data

    except Exception as e:
        logger.error(f"Failed to fetch/cache catalog for '{channel}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error fetching catalog from upstream API."
        )


def money(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def index_tax_types(catalog: dict) -> dict:
    # taxTypeId -> {"name": ..., "percentage": ...}
    return {
        t["taxTypeId"]: {"name": t["name"], "percentage": float(t["percentage"])}
        for t in catalog.get("taxTypes", [])
    }


def find_item(catalog_items: list, *, sku: str | None = None) -> dict | None:
    for it in catalog_items:
        if it.get("status") != "Active":
            continue
        if sku is not None and str(it.get("skuCode")) == str(sku):
            return it
    return None


def build_item_with_taxes(src_item: dict, tax_index: dict, qty: int) -> tuple[dict, float, float]:
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
        tax_on_base = (item_amount * rate) / 100.0

        if price_includes_tax:
            amount_included = money(tax_on_base)
            amount_excluded = 0.0
            total_tax_included += amount_included
        else:
            amount_included = 0.0
            amount_excluded = money(tax_on_base)
            total_tax_excluded += amount_excluded

        taxes.append({
            "name": meta["name"],
            "percentage": rate,
            "saleAmount": money(item_amount),
            "amountIncluded": amount_included if amount_included else 0.0,
            "amountExcluded": amount_excluded if amount_excluded else 0.0,
            "amount": money((amount_included or 0.0) + (amount_excluded or 0.0)),
        })

    item_total_amount = money(item_amount)
    line = {
        "shortName": src_item["itemName"],
        "skuCode": src_item["skuCode"],
        "quantity": qty,
        "unitPrice": money(unit_price),
        "itemAmount": item_total_amount,
        "itemTotalAmount": item_total_amount,
    }
    if taxes:
        if total_tax_included:
            line["taxAmountIncluded"] = money(total_tax_included)
        if total_tax_excluded:
            line["taxAmountExcluded"] = money(total_tax_excluded)
        line["taxes"] = taxes

    return line, total_tax_included, total_tax_excluded


def summarize_sale_taxes(items: list) -> list:
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
                "amount": 0.0
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
        for k in ["saleAmount", "itemTaxIncluded", "itemTaxExcluded", "chargeTaxIncluded",
                  "chargeTaxExcluded", "amountIncluded", "amountExcluded", "amount"]:
            v[k] = money(v[k])
    return list(agg.values())
