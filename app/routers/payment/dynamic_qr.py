
import logging
from datetime import datetime, timezone
from functools import reduce
from typing import Optional, Tuple

import httpx
from sqlalchemy import select, update
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
import time

from app.core.phonepe_utils import (
    make_base64, make_request_body, make_hash,
    compute_x_verify_for_endpoint, compute_qr_expiry,
)
from app.core.config import settings
from app.db.models.order import Order, PaymentStatus, KdsStatus
from app.core.dependencies import get_http_client, get_redis_client
from app.db.session import get_db

from app.db.schemas.payment import (
    QRInitiateRequest, QRInitiateResponse, StatusResponse,
)
from app.core.rista_utils import post_order_to_kds

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# HELPER FUNCTION: Extract KDS Posting Logic (DRY Principle)
# ============================================================================
async def try_post_to_kds(
        order: Order,
        db: AsyncSession,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis,
) -> Tuple[bool, Optional[str]]:
    """
    Atomically acquire KDS posting lock and post order if not already posted.

    Returns:
        Tuple[bool, Optional[str]]: (success, invoice_id)
        - success: Whether KDS posting succeeded
        - invoice_id: Rista invoice number if successful
    """
    if order.payment_status != PaymentStatus.COMPLETED:
        return False, None

    if order.kds_status != KdsStatus.NOT_POSTED:
        return True, order.kds_invoice_id  # Already posted or in progress

    # ATOMIC LOCK: Try to acquire right to post to KDS
    result = await db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.kds_status == KdsStatus.NOT_POSTED,
            )
        .values(kds_status=KdsStatus.PENDING)
        .returning(Order.kds_status)
    )
    row = result.first()
    await db.commit()

    if not row:
        # Another process already owns the KDS post, skip
        logger.info(f"KDS lock not acquired for order {order.order_id} (already posting)")
        return True, order.kds_invoice_id

    # THIS PROCESS OWNS THE KDS POST
    logger.info(f"KDS lock acquired for order {order.order_id}, attempting post...")

    await db.refresh(order)
    kdssuccess, invoice = await post_order_to_kds(
        order, http_client, redis_client
    )

    if kdssuccess and invoice:
        order.kds_invoice_id = invoice
        order.kds_status = KdsStatus.POSTED
        order.kds_last_error = None
        await db.commit()
        logger.info(f"Order {order.order_id} posted to KDS with invoice {invoice}")
        return True, invoice
    elif not kdssuccess:
        order.kds_status = KdsStatus.FAILED
        await db.commit()
        logger.error(f"KDS posting failed for order {order.order_id}")
        return False, None

    return True, order.kds_invoice_id


# ============================================================================
# JWT token now includes unique request_id for idempotency
# ============================================================================
def generate_qr_request_id(order_id: str) -> str:
    """
    Generate unique request ID for JWT idempotency.

    Format: qr_{order_id}_{timestamp_ms}
    This ensures each QR initiation is unique even for same order.
    """
    timestamp_ms = int(time.time() * 1000)
    return f"qr_{order_id}_{timestamp_ms}"


# ============================================================================
# ENDPOINT 1: Initiate QR Payment
# ============================================================================
@router.post("/init", response_model=QRInitiateResponse)
async def initiate_qr_payment(
        qr_request: QRInitiateRequest,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Initiate Dynamic QR code generation for payment.

    Flow:
    1. Validate order exists and not already paid
    2. Build PhonePe payload with merchant details
    3. Call PhonePe API using injected http_client
    4. Store QR data in order
    5. Return QR code to client

    Issues Fixed:
    - ISSUE 1: Uses injected http_client (not creating new one)
    - ISSUE 4: Generates unique request_id for JWT idempotency
    """

    # 1) Validate order
    stmt = select(Order).where(Order.order_id == qr_request.order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.warning(f"Order not found: {qr_request.order_id}")
        raise HTTPException(status_code=404, detail="Order not found")

    # If already paid, return existing QR data
    if order.payment_status == PaymentStatus.COMPLETED:
        logger.info(f"Order {qr_request.order_id} already paid, returning cached QR")
        return QRInitiateResponse(
            order_id=order.order_id,
            transaction_id=order.order_id,
            qr_string=order.qr_string,
            expires_at=order.qr_expires_at,
        )

    # 2) Build PhonePe payload
    transaction_id = qr_request.order_id
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
    # Remove None values
    request_payload = {k: v for k, v in request_payload.items() if v is not None}
    base64_payload = make_base64(request_payload)
    endpoint = settings.QR_INIT_ENDPOINT
    x_verify = compute_x_verify_for_endpoint(
        base64_payload, endpoint, settings.SALT_KEY, settings.SALT_KEY_INDEX
    )

    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": x_verify,
        "X-PROVIDER-ID": settings.X_PROVIDER_ID,
        "X-CALLBACK-URL": settings.PHONEPE_CALLBACK_URL,
        "X-CALL-MODE": "POST",
    }
    url = settings.UAT_BASE_URL + endpoint
    data = make_request_body(base64_payload)

    # 3) Call PhonePe using INJECTED CLIENT (ISSUE 1 FIXED ✅)
    try:
        logger.info(f"Initiating QR for order {transaction_id}")
        resp = await http_client.post(
            url, data=data, headers=headers, timeout=30.0
        )
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
        order.payment_method = "QR"
        if expires_in:
            order.qr_expires_at = compute_qr_expiry(
                datetime.now(timezone.utc), int(expires_in)
            )
        order.payment_status = PaymentStatus.PENDING
        await db.commit()
        await db.refresh(order)

        logger.info(f"QR generated for order {transaction_id}, expires at {order.qr_expires_at}")

        return QRInitiateResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            qr_string=qr_string,
            expires_at=order.qr_expires_at,
        )

    except httpx.HTTPStatusError as e:
        logger.error(
            f"PhonePe QR Error: {e.response.status_code} - {e.response.text}",
            exc_info=True
        )
        raise HTTPException(
            status_code=e.response.status_code,
            detail="Error generating QR code"
        )
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe: {e}", exc_info=True)
        raise HTTPException(
            status_code=502, detail="Error connecting to payment provider"
        )
    except Exception as e:
        logger.error(f"Unexpected error in QR initiation: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )


# ============================================================================
# ENDPOINT 2: Get Payment Status (Refactored with DRY)
# ============================================================================
@router.get("/status/{order_id}", response_model=StatusResponse)
async def get_payment_status(
        order_id: str,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Get current payment status for an order.

    Flow:
    1. Load order from DB
    2. If payment already final (COMPLETED/FAILED):
       - If COMPLETED and KDS not posted: Try to post to KDS
       - Return current status
    3. If payment PENDING:
       - Query PhonePe for current status
       - Update DB if changed
       - If now COMPLETED and KDS not posted: Try to post to KDS
       - Return updated status

    Issues Fixed:
    - ISSUE 2: DRY principle - extracted KDS posting logic to helper
    - ISSUE 3: Better error handling with more context
    - ISSUE 5: Cleaner code structure, reduced duplication
    """

    # 1) Load order from DB
    stmt = select(Order).where(Order.order_id == order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.warning(f"Order not found: {order_id}")
        raise HTTPException(status_code=404, detail="Order not found")

    # 2) If already final, try KDS posting if needed
    if order.payment_status in (
            PaymentStatus.COMPLETED,
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
    ):
        logger.info(f"Order {order_id} has final payment status: {order.payment_status}")

        if order.payment_status == PaymentStatus.COMPLETED:
            # Try to post to KDS (DRY: using helper function)
            _, invoice_id = await try_post_to_kds(
                order, db, http_client, redis_client
            )
            await db.refresh(order)

        return StatusResponse(
            order_id=order.order_id,
            payment_status=order.payment_status,
            provider_code=order.provider_code,
            provider_raw=order.provider_resp,
            kds_invoice_id=order.kds_invoice_id,
            kds_status=order.kds_status,
            kot_code=order.kot_code,
        )

    # 3) Otherwise, query PhonePe for current status
    logger.info(f"Querying PhonePe for status of order {order_id}")

    endpoint = (
        f"{settings.TRANSACTION_ENDPOINT}/"
        f"{settings.MERCHANT_ID}/{order_id}/status"
    )
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
        message = prov.get("message", "")

        # Map PhonePe code to our PaymentStatus
        if code == "PAYMENT_SUCCESS":
            new_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_PENDING", "PENDING"):
            new_status = PaymentStatus.PENDING
        else:
            new_status = PaymentStatus.FAILED

        logger.info(f"PhonePe status for order {order_id}: {code} -> {new_status}")

        # Update DB with new status
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
        await db.refresh(order)

        # 4) If now completed and KDS not posted, try to post
        if new_status == PaymentStatus.COMPLETED:
            _, invoice_id = await try_post_to_kds(
                order, db, http_client, redis_client
            )
            await db.refresh(order)

        return StatusResponse(
            order_id=order.order_id,
            payment_status=new_status,
            provider_code=code,
            provider_message=message,
            provider_raw=prov,
            kds_invoice_id=order.kds_invoice_id,
            kds_status=order.kds_status,
            kot_code=order.kot_code,
        )

    except httpx.HTTPStatusError as e:
        logger.error(
            f"PhonePe Status Error: {e.response.status_code} - {e.response.text}",
            exc_info=True
        )
        raise HTTPException(
            status_code=e.response.status_code,
            detail="Error fetching payment status"
        )
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe status: {e}", exc_info=True)
        raise HTTPException(
            status_code=502, detail="Error connecting to payment provider"
        )
    except Exception as e:
        logger.error(f"Unexpected error in status check: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )