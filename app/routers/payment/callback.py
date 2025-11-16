import json
import base64
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
import redis.asyncio as redis

from app.core.phonepe_utils import (
    verify_phonepe_callback_hash,
)

from app.core.dependencies import get_http_client, get_redis_client
from app.services.payment_service import process_webhook_in_background

logger = logging.getLogger(__name__)
router = APIRouter()

# noinspection PyTypeChecker
@router.post("/phonepe")
async def handle_phonepe_callback(
        request: Request,
        background_tasks: BackgroundTasks,
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info("Received PhonePe webhook...")

    # --- All this validation is FAST ---
    x_verify_header = request.headers.get("X-VERIFY")
    try:
        body_json = await request.json()
        base64_payload = body_json.get("response")
        if not base64_payload:
            raise HTTPException(
                status_code=400,
                detail="Invalid callback payload: 'response' key missing",
            )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid callback body")

    calculated_hash = verify_phonepe_callback_hash(base64_payload)
    if calculated_hash != x_verify_header:
        logger.warning("Callback signature verification FAILED!")
        raise HTTPException(
            status_code=401, detail="Webhook signature verification failed"
        )

    logger.info("Webhook signature verified.")
    try:
        payload_str = base64.urlsafe_b64decode(base64_payload).decode("utf-8")
        payload = json.loads(payload_str)
        logger.info(f"Decoded Payload: {payload}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload encoding")

    data_payload = payload.get("data", {})
    merchant_order_id = data_payload.get("merchantOrderId")
    code = payload.get("code")

    if not merchant_order_id:
        raise HTTPException(
            status_code=400, detail="Missing merchantOrderId in payload"
        )

    # 3. Add the SLOW work to the background
    background_tasks.add_task(
        process_webhook_in_background,
        merchant_order_id=merchant_order_id,
        code=code,
        payload=payload,
        http_client=http_client,
        redis_client=redis_client,
    )

    # 4. IMMEDIATELY return 200 OK
    return {"status": "ok", "message": "Webhook acknowledged"}

