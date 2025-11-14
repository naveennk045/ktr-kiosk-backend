import time
from decimal import Decimal, ROUND_HALF_UP
import jwt
import logging
import httpx
import json
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
import redis.asyncio as redis
from datetime import datetime, timezone

from .config import settings
from ..db.models.order import Order

logger = logging.getLogger(__name__)


def generate_jwt_token(request_id: str | None = None):
    """
    Generate JWT token for API authentication using HS256 algorithm.

    Args:
        request_id: Unique request identifier (required for POST/PUT/DELETE)
    """
    token_creation_time = int(time.time())
    payload = {
        "iss": settings.PI_KEY,
        "iat": token_creation_time
    }

    # Add jti for POST requests to ensure uniqueness
    if request_id:
        payload["jti"] = f"{request_id}_{token_creation_time}"

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


async def get_catalog_data(
        channel: str,
        redis_client: redis.Redis,
        http_client: httpx.AsyncClient
) -> dict:
    """
    Get catalog data from cache or fetch from Rista API.
    """
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
        "x-api-key": settings.PI_KEY,
        "x-api-token": token,
        "content-type": 'application/json'
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
    """Round to 2 decimal places for currency."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def index_tax_types(catalog: dict) -> dict:
    """Create a lookup dictionary for tax types."""
    return {
        t["taxTypeId"]: {"name": t["name"], "percentage": float(t["percentage"])}
        for t in catalog.get("taxTypes", [])
    }


def find_item(catalog_items: list, *, sku: str | None = None) -> dict | None:
    """Find an active item in catalog by SKU."""
    for it in catalog_items:
        if it.get("status") != "Active":
            continue
        if sku is not None and str(it.get("skuCode")) == str(sku):
            return it
    return None


def calculate_tax_amounts(sale_amount: float, tax_percentage: float, price_includes_tax: bool) -> tuple[float, float]:
    """
    Calculate tax amounts based on whether tax is included or excluded.

    Returns: (amountIncluded, amountExcluded)
    """
    if price_includes_tax:
        # Tax included: Tax = Amount × Tax% / (100 + Tax%)
        tax_amount = (sale_amount * tax_percentage) / (100 + tax_percentage)
        return money(tax_amount), 0.0
    else:
        # Tax excluded: Tax = Amount × Tax% / 100
        tax_amount = (sale_amount * tax_percentage) / 100
        return 0.0, money(tax_amount)


def build_item_with_taxes(src_item: dict, tax_index: dict, qty: int) -> tuple[dict, float, float]:
    """
    Build a sale item with proper tax calculations.

    Returns: (item_dict, total_tax_included, total_tax_excluded)
    """
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
        amount_included, amount_excluded = calculate_tax_amounts(item_amount, rate, price_includes_tax)

        total_tax_included += amount_included
        total_tax_excluded += amount_excluded

        taxes.append({
            "name": meta["name"],
            "percentage": rate,
            "saleAmount": money(item_amount),
            "amountIncluded": amount_included,
            "amountExcluded": amount_excluded,
            "amount": money(amount_included + amount_excluded),
        })

    item_total_amount = money(item_amount)
    line = {
        "shortName": src_item["itemName"],
        "skuCode": src_item["skuCode"],
        "quantity": qty,
        "unitPrice": money(unit_price),
        "itemAmount": item_total_amount,
        "itemNature": "Service",  # Or get from catalog if available
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
    """Aggregate taxes across all items."""
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


async def check_existing_sale(
        order_id: str,
        http_client: httpx.AsyncClient
) -> tuple[bool, str | None]:
    """
    Check if a sale already exists in Rista KDS for this order.

    Returns: (exists: bool, invoice_id: str | None)
    """
    try:
        token = await run_in_threadpool(generate_jwt_token)

        headers = {
            "x-api-key": settings.PI_KEY,
            "x-api-token": token,
            "content-type": "application/json"
        }

        # Query by source transaction ID
        params = {"orderTransactionId": order_id}
        url = f"{settings.RISTA_BASE_URL}/sale"

        response = await http_client.get(url, headers=headers, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            # Check if we got results
            if data and isinstance(data, list) and len(data) > 0:
                invoice_id = data[0].get("invoiceNumber")
                logger.info(f"Sale already exists for order {order_id}. Invoice: {invoice_id}")
                return True, invoice_id
            return False, None
        else:
            # If query fails, assume doesn't exist
            return False, None

    except Exception as e:
        logger.warning(f"Error checking existing sale for {order_id}: {e}")
        # On error, assume doesn't exist and try to post
        return False, None


async def post_order_to_kds(
        order: Order,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis
) -> tuple[bool, str | None]:
    """
    Post order to Rista KDS with idempotency.

    Returns: (success: bool, invoice_id: str | None)
    """
    logger.info(f"Attempting to post order {order.order_id} to KDS...")

    # 1. Check if sale already exists (idempotency check)
    exists, existing_invoice = await check_existing_sale(order.order_id, http_client)
    if exists:
        logger.info(f"Order {order.order_id} already posted to KDS. Invoice: {existing_invoice}")
        return True, existing_invoice

    # 2. Get catalog data
    try:
        catalog = await get_catalog_data(order.channel, redis_client, http_client)
    except Exception as e:
        logger.error(f"Failed to get catalog for order {order.order_id}: {e}")
        return False, None

    if not catalog.get("items"):
        logger.error(f"Empty catalog for channel {order.channel}")
        return False, None

    tax_index = index_tax_types(catalog)
    catalog_items = catalog.get("items", [])

    # 3. Build sale items
    sale_items = []
    sum_item_total = 0.0
    sum_tax_inc = 0.0
    sum_tax_exc = 0.0

    for item_spec in order.items:
        src_item = find_item(catalog_items, sku=item_spec.get("sku_code"))
        if not src_item:
            logger.error(f"Item SKU {item_spec.get('sku_code')} not found in catalog")
            return False, None

        line, tax_inc, tax_exc = build_item_with_taxes(src_item, tax_index, item_spec["quantity"])
        sale_items.append(line)
        sum_item_total += float(line["itemTotalAmount"])
        sum_tax_inc += float(tax_inc)
        sum_tax_exc += float(tax_exc)

    # 4. Build sale payload
    sale_body = {
        "branchCode": settings.BRANCH_CODE,
        "channel": order.channel,
        "status": "Closed",  # Payment is complete
        "sourceInfo": {
            "source": order.channel,
            "orderTransactionId": order.order_id,  # This ensures idempotency
            "invoiceNumber": order.order_id,
            "invoiceDate": datetime.now(timezone.utc).isoformat()
        },
        "items": sale_items,
        "itemTotalAmount": money(sum_item_total),
        "payments": [
            {
                "mode": order.payment_method or "Digital",
                "amount": money(order.total_amount_include_tax),
                "reference": order.provider_txn_id or order.order_id,
                "postedDate": datetime.now(timezone.utc).isoformat()
            }
        ]
    }

    if sum_tax_inc:
        sale_body["taxAmountIncluded"] = money(sum_tax_inc)
    if sum_tax_exc:
        sale_body["taxAmountExcluded"] = money(sum_tax_exc)

    bill_amount = sum_item_total + sum_tax_exc
    sale_body["billAmount"] = money(bill_amount)
    sale_body["roundOffAmount"] = 0.0
    sale_body["billRoundedAmount"] = money(bill_amount)
    sale_body["tipAmount"] = 0.0
    sale_body["totalAmount"] = money(order.total_amount_include_tax)

    sale_taxes = summarize_sale_taxes(sale_items)
    if sale_taxes:
        sale_body["taxes"] = sale_taxes

    # 5. Generate JWT with unique request ID
    try:
        request_id = f"kds_{order.order_id}_{int(time.time() * 1000)}"
        token = await run_in_threadpool(generate_jwt_token, request_id)
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        return False, None

    headers = {
        "x-api-key": settings.PI_KEY,
        "x-api-token": token,
        "content-type": "application/json",
        "accept": "application/json",
    }

    url = f"{settings.RISTA_BASE_URL}/sale"
    logger.info(f"Posting order {order.order_id} to KDS...")

    try:
        resp = await http_client.post(url, headers=headers, json=sale_body, timeout=30)
        resp.raise_for_status()

        resp_data = resp.json()
        invoice_id = resp_data.get("invoiceNumber")

        logger.info(f"✅ KDS Post Success: {order.order_id} -> Invoice: {invoice_id}")
        return True, invoice_id

    except httpx.HTTPStatusError as e:
        # Handle 409 Conflict gracefully
        if e.response.status_code == 409:
            logger.warning(f"409 Conflict for {order.order_id}. Checking if order exists...")
            # Double-check if the order actually exists
            exists, existing_invoice = await check_existing_sale(order.order_id, http_client)
            if exists:
                logger.info(f"Confirmed: Order {order.order_id} exists. Invoice: {existing_invoice}")
                return True, existing_invoice
            else:
                logger.error(f"409 Conflict but order doesn't exist. This shouldn't happen.")
                return False, None

        logger.error(f"KDS Post Failed: {e.response.status_code} - {e.response.text}")
        return False, None

    except httpx.RequestError as e:
        logger.error(f"Network error posting to KDS: {e}")
        return False, None
