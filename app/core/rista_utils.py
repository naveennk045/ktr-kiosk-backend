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
from ..db.models.order import Order

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


async def post_order_to_kds(
        order: Order,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis
) -> tuple[bool, str | None]:
    """ Builds the Rista/KDS payload from the Order object and posts it. """
    logger.info(f"Building KDS payload for order {order.order_id}...")
    catalog = await get_catalog_data(order.channel, redis_client, http_client)
    if not catalog.get("items"):
        logger.error(f"KDS Post Failed: Could not get catalog data for channel {order.channel}")
        return False, None

    tax_index = index_tax_types(catalog)
    catalog_items = catalog.get("items", [])
    sale_items, sum_item_total, sum_tax_inc, sum_tax_exc = [], 0.0, 0.0, 0.0

    for item_spec in order.items:
        src_item = find_item(catalog_items, sku=item_spec.get("sku_code"))
        if not src_item:
            logger.error(f"KDS Post Failed: Item SKU {item_spec.get('sku_code')} not found in catalog.")
            return False, None
        line, tax_inc, tax_exc = build_item_with_taxes(src_item, tax_index, item_spec["quantity"])
        sale_items.append(line)
        sum_item_total += float(line["itemTotalAmount"])
        sum_tax_inc += float(tax_inc)
        sum_tax_exc += float(tax_exc)

    sale_body = {
        "branchCode": settings.BRANCH_CODE, "channel": order.channel, "status": "Closed",
        "items": sale_items, "itemTotalAmount": money(sum_item_total),
    }
    if sum_tax_inc: sale_body["taxAmountIncluded"] = money(sum_tax_inc)
    if sum_tax_exc: sale_body["taxAmountExcluded"] = money(sum_tax_exc)

    bill_amount = sum_item_total + sum_tax_exc
    sale_body.update({
        "billAmount": money(bill_amount), "roundOffAmount": 0.0,
        "billRoundedAmount": money(bill_amount), "tipAmount": 0.0,
        "totalAmount": money(bill_amount)
    })

    if sale_taxes := summarize_sale_taxes(sale_items):
        sale_body["taxes"] = sale_taxes

    try:
        token = await run_in_threadpool(generate_jwt_token)
    except Exception as e:
        logger.error(f"KDS Post Failed: JWT generation error: {e}")
        return False, None

    headers = {
        "x-api-key": settings.PI_KEY, "x-api-token": token,
        "content-type": "application/json", "accept": "application/json",
    }
    url = f"{settings.RISTA_BASE_URL}/sale"
    logger.info(f"Posting to KDS for order {order.order_id}...")

    try:
        resp = await http_client.post(url, headers=headers, json=sale_body, timeout=30)
        resp.raise_for_status()
        resp_data = resp.json()
        invoice_id = resp_data.get("invoiceNumber")
        logger.info(f"KDS Post Success for {order.order_id}. Invoice ID: {invoice_id}")
        return True, invoice_id
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            logger.warning(f"KDS Post for {order.order_id} returned 409 Conflict. Treating as success.")
            return True, None
        logger.error(f"KDS Post Failed (API Error): {e.response.status_code} - {e.response.text}")
        return False, None
    except httpx.RequestError as e:
        logger.error(f"KDS Post Failed (Network Error): {e}")
        return False, None