import json
import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
import httpx
import redis.asyncio as redis

from app.core.dependencies import get_http_client, get_redis_client
from app.utils.phonepe import verify_phonepe_callback_hash
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/phonepe")
async def handle_callback(
        request: Request,
        background_tasks: BackgroundTasks,
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client)
):
    x_verify = request.headers.get("X-VERIFY")
    try:
        body = await request.json()
        base64_payload = body.get("response")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not base64_payload:
        raise HTTPException(status_code=400, detail="Missing response payload")

    calculated_hash = verify_phonepe_callback_hash(base64_payload)
    if calculated_hash != x_verify:
        logger.warning(f"Signature verification failed. Expected: {calculated_hash}, Got: {x_verify}")
        raise HTTPException(status_code=401, detail="Invalid Signature")

    try:
        decoded_str = base64.b64decode(base64_payload).decode("utf-8")
        payload = json.loads(decoded_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Decoding failed")

    data = payload.get("data", {})
    merchant_order_id = data.get("merchantOrderId")
    code = payload.get("code")

    if merchant_order_id:
        background_tasks.add_task(
            PaymentService.run_webhook_in_background,
            merchant_order_id=merchant_order_id,
            code=code,
            payload=payload,
            http_client=http_client,
            redis_client=redis_client
        )
    else:
        logger.warning("Callback received without merchantOrderId")

    return {"status": "ok"}
