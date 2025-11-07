import httpx
import redis.asyncio as redis
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_http_client, get_redis_client
from app.db.postgres import get_db
from app.core.rista_utils import generate_jwt_token
from app.db.models.order import Order, PaymentStatus
from app.db.schemas.order import OrderCreateRequest, OrderCreateResponse

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_catalog_data(
        channel: str,
        redis_client: redis.Redis,
        http_client: httpx.AsyncClient
) -> dict:
    """
    Helper function to get catalog data, from cache or by fetching from Rista.
    This is the logic from your get_catalog endpoint, made reusable.
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


# noinspection Pydantic
@router.post("/", response_model=OrderCreateResponse)
async def create_order(
    request: OrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Creates a new order.
    1. Fetches catalog data from Redis (or Rista API if cache is empty).
    2. Validates every item SKU and re-calculates the price.
    3. Saves the order to the Postgres-SQL database with items in a JSON field.
    """

    # 1. Get trusted catalog data
    catalog_data = await _get_catalog_data(request.channel, redis_client, http_client)

    # 2. Build fast-lookup maps for validation
    sku_map = {item['skuCode']: item for item in catalog_data.get('items', [])}
    tax_map = {tax['taxTypeId']: tax['percentage'] for tax in catalog_data.get('taxTypes', [])}

    # 3. Recalculate totals (NEVER trust frontend totals)
    backend_total_exclude_tax = 0.0
    backend_total_include_tax = 0.0
    items_for_db = []  # List to store item details for the JSONB column

    # Log the received totals for comparison/auditing if needed
    logger.info(f"Received order for channel '{request.channel}' with "
                f"frontend totals (excl/incl): {request.total_amount_exclude_tax} / "
                f"{request.total_amount_include_tax}. Recalculating...")

    for item in request.items:
        item_details = sku_map.get(item.sku_code)
        if not item_details:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid item SKU code: {item.sku_code}"
            )

        unit_price = item_details.get('price', 0)
        item_total_price = unit_price * item.quantity

        item_tax = 0.0
        if not item_details.get('isPriceIncludesTax', False):
            for tax_id in item_details.get('taxTypeIds', []):
                tax_percentage = tax_map.get(tax_id, 0)
                item_tax += (item_total_price * (tax_percentage / 100))

        # Add to grand totals
        backend_total_exclude_tax += item_total_price
        backend_total_include_tax += (item_total_price + item_tax)

        # Add item details to the list for the JSONB field
        items_for_db.append({
            "sku_code": item.sku_code,
            "item_name": item_details.get('itemName'),
            "quantity": item.quantity,
            "unit_price": unit_price
        })

    # 4. Save to Database
    try:
        new_order = Order(
            channel=request.channel,
            items=items_for_db,
            total_amount_exclude_tax=round(backend_total_exclude_tax, 2),
            total_amount_include_tax=round(backend_total_include_tax, 2),
            payment_status=PaymentStatus.PENDING,
        )

        db.add(new_order)
        await db.flush()  # assign PK (new_order.id) without committing
        await db.commit()
        await db.refresh(new_order)

    except Exception as e:
        await db.rollback()  # <- await in async
        logger.error(f"Database error creating order: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save order to database.",
        )

    return OrderCreateResponse(
        order_id=new_order.id,
        amount_with_tax=new_order.total_amount_include_tax,
        amount_without_tax=new_order.total_amount_exclude_tax,
    )