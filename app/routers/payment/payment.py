import json
import base64
import logging
from datetime import datetime, timezone
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal, ROUND_HALF_UP

from app.core.phonepe_utils import (
    make_base64, make_request_body, make_hash,
    compute_x_verify_for_endpoint, compute_qr_expiry,
    verify_phonepe_callback_hash,
)
from app.core.rista_utils import (
    generate_jwt_token, get_catalog_data, money, index_tax_types,
    find_item, summarize_sale_taxes, build_item_with_taxes
)
from app.core.config import settings
from app.db.models.order import Order, PaymentStatus
from app.core.dependencies import get_http_client, get_redis_client
from app.db.postgres import get_db
import redis.asyncio as redis

logger = logging.getLogger(__name__)
router = APIRouter()


class QRInitiateRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., ge=1)


class QRInitiateResponse(BaseModel):
    order_id: str
    transaction_id: str
    qr_string: str | None = None
    expires_at: datetime | None = None
    provider: str = "PhonePe"


@router.post("/qr/init", response_model=QRInitiateResponse)
async def initiate_qr_payment(
        qr_request: QRInitiateRequest,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    # 1) Validate order
    stmt = select(Order).where(Order.order_id == qr_request.order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status == PaymentStatus.COMPLETED:
        return QRInitiateResponse(
            order_id=order.order_id,
            transaction_id=order.order_id,
            qr_string=order.qr_string,
            expires_at=order.qr_expires_at,
        )

    # 2) Build PhonePe payload
    transaction_id = qr_request.order_id  # using order_id as transactionId
    request_payload = {
        "amount": qr_request.amount_paise,
        "expiresIn": 180,
        "merchantId": settings.MERCHANT_ID,
        "merchantOrderId": transaction_id,
        "storeId": getattr(settings, "STORE_ID", None),
        "terminalId": getattr(settings, "TERMINAL_ID", None),
        "transactionId": transaction_id,
        "message": f"Payment for order {transaction_id}",
    }
    # Remove None keys
    request_payload = {k: v for k, v in request_payload.items() if v is not None}

    base64_payload = make_base64(request_payload)

    endpoint = settings.QR_INIT_ENDPOINT
    x_verify = compute_x_verify_for_endpoint(base64_payload, endpoint, settings.SALT_KEY, settings.SALT_KEY_INDEX)

    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": x_verify,
        "X-PROVIDER-ID": settings.X_PROVIDER_ID,
        "X-CALLBACK-URL": settings.PHONEPE_CALLBACK_URL,
        "X-CALL-MODE": "POST",
    }
    url = settings.UAT_BASE_URL + endpoint
    data = make_request_body(base64_payload)

    # 3) Call PhonePe
    try:
        resp = await http_client.post(url, data=data, headers=headers, timeout=30.0)
        resp.raise_for_status()
        payload = resp.json()

        code = payload.get("code")
        data_node = payload.get("data", {}) or {}
        qr_string = data_node.get("qrCode") or data_node.get("qrString")
        expires_in = data_node.get("expiresIn") or request_payload["expiresIn"]

        # 4) Persist QR metadata
        order.provider_code = code
        order.provider_txn_id = transaction_id
        order.provider_resp = payload
        order.qr_string = qr_string
        if expires_in:
            order.qr_expires_at = compute_qr_expiry(datetime.now(timezone.utc), int(expires_in))
        order.payment_status = PaymentStatus.PENDING
        await db.commit()

        return QRInitiateResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            qr_string=qr_string,
            expires_at=order.qr_expires_at,
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"PhonePe QR Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.json())
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe: {e}")
        raise HTTPException(status_code=502, detail="Error connecting to payment provider")


async def post_order_to_kds(
        order: Order,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis
) -> tuple[bool, str | None]:
    """
    Builds the Rista/KDS payload and posts it.
    Returns: (bool: success, str: invoice_id | None)
    """
    pass


# ---  PhonePe Webhook Endpoint ---
@router.post("/webhook/phonepe")
async def handle_phonepe_callback(
        request: Request,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client)
):
    logger.info("Received PhonePe webhook...")
    x_verify_header = request.headers.get("X-VERIFY")
    try:
        body_json = await request.json()
        base64_payload = body_json.get("response")
        if not base64_payload:
            raise HTTPException(status_code=400, detail="Invalid callback payload: 'response' key missing")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid callback body")

    calculated_hash = verify_phonepe_callback_hash(base64_payload)
    if calculated_hash != x_verify_header:
        logger.warning(f"Callback signature verification FAILED!")
        raise HTTPException(status_code=401, detail="Webhook signature verification failed")

    logger.info("Webhook signature verified.")
    try:
        payload_str = base64.urlsafe_b64decode(base64_payload).decode("utf-8")
        payload = json.loads(payload_str)
        logger.info(f"Decoded Payload: {payload}")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid payload encoding")

    data_payload = payload.get("data", {})
    merchant_order_id = data_payload.get("merchantOrderId")
    code = payload.get("code")
    if not merchant_order_id:
        raise HTTPException(status_code=400, detail="Missing merchantOrderId in payload")

    try:
        async with db.begin():
            stmt = select(Order).where(
                Order.order_id == merchant_order_id
            ).with_for_update()

            result = await db.execute(stmt)
            order = result.scalar_one_or_none()

            if not order:
                logger.error(f"Order {merchant_order_id} not found in DB.")
                return {"status": "ok", "message": "Order not found but acknowledged"}

            if order.payment_status == PaymentStatus.COMPLETED:
                logger.info(f"Order {merchant_order_id} already completed. Skipping duplicate webhook.")
                return {"status": "ok"}

            order.provider_code = code
            order.provider_resp = payload

            if code == "PAYMENT_SUCCESS":
                logger.info(f"Payment success for {merchant_order_id}. Updating DB...")
                order.payment_status = PaymentStatus.COMPLETED

                # kds_success, invoice_id = await post_order_to_kds(order, http_client, redis_client)
                #
                # if kds_success:
                #     if invoice_id:
                #         logger.info(f"KDS Invoice ID for {merchant_order_id}: {invoice_id}")
                #         order.kds_invoice_id = invoice_id  # Save to DB (if you added the column)
                #     else:
                #         logger.warning(
                #             f"KDS post for {merchant_order_id} was successful (or 409), but no invoice ID was returned.")
                # else:
                #     logger.error(f"CRITICAL: Order {merchant_order_id} PAID but FAILED to post to KDS.")

            elif code in ("PAYMENT_PENDING", "PENDING"):
                order.payment_status = PaymentStatus.PENDING
            else:
                order.payment_status = PaymentStatus.FAILED

    except Exception as e:
        logger.error(f"Error processing webhook for {merchant_order_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error processing order")

    return {"status": "ok"}


class StatusResponse(BaseModel):
    order_id: str
    payment_status: PaymentStatus
    provider_code: str | None = None
    provider_message: str | None = None
    provider_raw: dict | None = None


@router.get("/status/{order_id}", response_model=StatusResponse)
async def get_payment_status(
        order_id: str,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    # 1) Prefer DB if finalized
    stmt = select(Order).where(Order.order_id == order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status in (PaymentStatus.COMPLETED, PaymentStatus.FAILED, PaymentStatus.REFUNDED):
        return StatusResponse(
            order_id=order.order_id,
            payment_status=order.payment_status,
            provider_code=order.provider_code,
            provider_message=None,
            provider_raw=order.provider_resp,
        )

    # 2) Otherwise, query PhonePe and update DB
    endpoint = f"{settings.TRANSACTION_ENDPOINT}/{settings.MERCHANT_ID}/{order_id}/status"
    x_verify = make_hash(endpoint + settings.SALT_KEY) + f"###{settings.SALT_KEY_INDEX}"

    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": x_verify,
        "X-PROVIDER-ID": settings.X_PROVIDER_ID,
    }
    url = settings.UAT_BASE_URL + endpoint

    try:
        resp = await http_client.get(url, headers=headers, timeout=30.0)
        resp.raise_for_status()
        prov = resp.json()

        code = prov.get("code")
        message = prov.get("message")

        # Map to internal status
        if code == "PAYMENT_SUCCESS":
            new_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_PENDING", "PENDING"):
            new_status = PaymentStatus.PENDING
        else:
            new_status = PaymentStatus.FAILED

        # Persist
        await db.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(
                payment_status=new_status,
                provider_code=code,
                provider_resp=prov,
            )
        )
        await db.commit()

        return StatusResponse(
            order_id=order.order_id,
            payment_status=new_status,
            provider_code=code,
            provider_message=message,
            provider_raw=prov,
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"PhonePe Status Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.json())
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe status: {e}")
        raise HTTPException(status_code=502, detail="Error connecting to payment provider")
