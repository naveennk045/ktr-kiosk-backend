import json
import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
import httpx
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_http_client, get_redis_client
from app.db.models.order import Order
from app.db.models.store import StorePhonePeCredentials
from app.db.session import get_db
from app.utils.phonepe import verify_phonepe_callback_hash
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/phonepe")
async def handle_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncSession = Depends(get_db),
):
    x_verify = request.headers.get("X-VERIFY")
    try:
        body = await request.json()
        base64_payload = body.get("response")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not base64_payload:
        raise HTTPException(status_code=400, detail="Missing response payload")

    try:
        decoded_str = base64.b64decode(base64_payload).decode("utf-8")
        payload_outer = json.loads(decoded_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Decoding failed")

    data = payload_outer.get("data", {}) or {}
    merchant_order_id = data.get("merchantOrderId")

    salt_key = None
    salt_index = None
    if merchant_order_id:
        ostmt = select(Order).where(Order.order_id == merchant_order_id)
        order = (await db.execute(ostmt)).scalar_one_or_none()
        if order:
            ppstmt = select(StorePhonePeCredentials).where(
                StorePhonePeCredentials.store_id == order.store_id
            )
            pp = (await db.execute(ppstmt)).scalar_one_or_none()
            if pp:
                salt_key = pp.salt_key
                salt_index = pp.salt_key_index

    try:
        calculated_hash = verify_phonepe_callback_hash(
            base64_payload, salt_key=salt_key, salt_key_index=salt_index
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    if calculated_hash != x_verify:
        logger.warning(
            "PhonePe callback signature verification failed | order_id=%s",
            merchant_order_id,
        )
        raise HTTPException(status_code=401, detail="Invalid Signature")

    code = payload_outer.get("code")

    if merchant_order_id:
        logger.info("PhonePe callback accepted | order_id=%s | code=%s", merchant_order_id, code)
        background_tasks.add_task(
            PaymentService.run_webhook_in_background,
            merchant_order_id=merchant_order_id,
            code=code,
            payload=payload_outer,
            http_client=http_client,
            redis_client=redis_client,
        )
    else:
        logger.warning("PhonePe callback received without merchantOrderId")

    return {"status": "ok"}
