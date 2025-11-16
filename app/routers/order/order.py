
import uuid
import logging

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_http_client, get_redis_client
from app.db.postgres import get_db
from app.db.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.core.rista_utils import get_catalog_data
from app.core.kot_utils import generate_kot
from app.db.models.order import Order, PaymentStatus, KdsStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=OrderCreateResponse)
async def create_order(
        request: OrderCreateRequest,
        db: AsyncSession = Depends(get_db),
        redis_client: redis.Redis = Depends(get_redis_client),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Create a new order:

    - Validates items against Rista catalog
    - Recalculates totals on backend
    - Generates:
        * order_id = UUID-based business/payment ID
        * KOT = daily running number (ktr-1, ktr-2, ...)
    """

    # 1. Get trusted catalog data
    catalog_data = await get_catalog_data(request.channel, redis_client, http_client)
    sku_map = {item["skuCode"]: item for item in catalog_data.get("items", [])}
    tax_map = {
        tax["taxTypeId"]: tax["percentage"]
        for tax in catalog_data.get("taxTypes", [])
    }

    # 2. Recalculate totals
    backend_total_exclude_tax = 0.0
    backend_total_include_tax = 0.0
    items_for_db: list[dict] = []

    logger.info(
        "Received order for channel '%s' with frontend totals (excl/incl): %s / %s. "
        "Recalculating...",
        request.channel,
        request.total_amount_exclude_tax,
        request.total_amount_include_tax,
    )

    for item in request.items:
        item_details = sku_map.get(item.sku_code)
        if not item_details:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid item SKU code: {item.sku_code}",
            )

        unit_price = item_details.get("price", 0.0)
        item_total_price = unit_price * item.quantity
        item_tax = 0.0

        # If price doesn't include tax, calculate tax using catalog taxTypeIds
        if not item_details.get("isPriceIncludesTax", False):
            for tax_id in item_details.get("taxTypeIds", []):
                tax_percentage = tax_map.get(tax_id, 0.0)
                item_tax += item_total_price * (tax_percentage / 100.0)

        backend_total_exclude_tax += item_total_price
        backend_total_include_tax += item_total_price + item_tax

        items_for_db.append(
            {
                "sku_code": item.sku_code,
                "item_name": item_details.get("itemName"),
                "quantity": item.quantity,
                "unit_price": unit_price,
            }
        )

    try:
        # 3. Get next primary key from sequence (for integer 'id')
        next_id_stmt = select(func.nextval("orders_id_seq"))
        next_id_result = await db.execute(next_id_stmt)
        next_id = next_id_result.scalar_one()

        # 4. Generate global order_id (UUID based)
        #    This is what you use as PhonePe merchantOrderId and Rista orderTransactionId
        generated_order_id = f"ord-{uuid.uuid4().hex}"
        # If you prefer plain UUID: generated_order_id = str(uuid.uuid4())

        # 5. Generate KOT for today (ktr-1, ktr-2, ...)
        kot_date, kot_number, kot_code = await generate_kot(db)

        # 6. Create the Order row
        new_order = Order(
            id=next_id,
            order_id=generated_order_id,
            channel=request.channel,
            items=items_for_db,
            total_amount_exclude_tax=round(backend_total_exclude_tax, 2),
            total_amount_include_tax=round(backend_total_include_tax, 2),
            payment_status=PaymentStatus.PENDING,
            payment_method=None,  # set later by QR/EDC init

            kot_date=kot_date,
            kot_number=kot_number,
            kot_code=kot_code,
            kds_status=KdsStatus.NOT_POSTED,
        )

        db.add(new_order)
        await db.commit()
        await db.refresh(new_order)

    except Exception as e:
        await db.rollback()
        logger.error("Database error creating order: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save order to database.",
        )

    # 7. Return business order_id + server-side totals + KOT
    return OrderCreateResponse(
        order_id=new_order.order_id,
        amount_with_tax=new_order.total_amount_include_tax,
        amount_without_tax=new_order.total_amount_exclude_tax,
        kot_code=new_order.kot_code,
    )