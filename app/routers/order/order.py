import httpx
import redis.asyncio as redis
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.dependencies import get_http_client, get_redis_client
from app.db.postgres import get_db
from app.db.models.order import Order, PaymentStatus
from app.db.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.core.rista_utils import get_catalog_data

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=OrderCreateResponse)
async def create_order(
        request: OrderCreateRequest,
        db: AsyncSession = Depends(get_db),
        redis_client: redis.Redis = Depends(get_redis_client),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    # 1. Get trusted catalog data
    catalog_data = await get_catalog_data(request.channel, redis_client, http_client)

    # 2. Build fast-lookup maps
    sku_map = {item['skuCode']: item for item in catalog_data.get('items', [])}
    tax_map = {tax['taxTypeId']: tax['percentage'] for tax in catalog_data.get('taxTypes', [])}

    # 3. Recalculate totals
    backend_total_exclude_tax = 0.0
    backend_total_include_tax = 0.0
    items_for_db = []

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
        backend_total_exclude_tax += item_total_price
        backend_total_include_tax += (item_total_price + item_tax)
        items_for_db.append({
            "sku_code": item.sku_code,
            "item_name": item_details.get('itemName'),
            "quantity": item.quantity,
            "unit_price": unit_price
        })

    # 4. Save to Database
    try:
        # 1. Get the next available primary key from the sequence
        next_id_stmt = select(func.nextval('orders_id_seq'))
        next_id_result = await db.execute(next_id_stmt)
        next_id = next_id_result.scalar_one()

        # 2. Create your human-readable KOT ID
        generated_kot_id = f"ktr-{next_id}"

        # 3. Create the order object WITH ALL required fields
        new_order = Order(
            id=next_id,
            order_id=generated_kot_id,
            channel=request.channel,
            items=items_for_db,
            total_amount_exclude_tax=round(backend_total_exclude_tax, 2),
            total_amount_include_tax=round(backend_total_include_tax, 2),
            payment_status=PaymentStatus.PENDING,
        )

        db.add(new_order)

        # 4. Commit the transaction
        await db.commit()

        # 5. Refresh to get DB-generated timestamps (like created_at)
        await db.refresh(new_order)

    except Exception as e:
        await db.rollback()
        logger.error(f"Database error creating order: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save order to database.",
        )

    # Return the clean KOT ID
    return OrderCreateResponse(
        order_id=new_order.order_id,
        amount_with_tax=new_order.total_amount_include_tax,
        amount_without_tax=new_order.total_amount_exclude_tax,
    )
