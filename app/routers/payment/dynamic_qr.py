import logging
from datetime import datetime, timezone
import httpx
from sqlalchemy import select, update
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.phonepe_utils import (
    make_base64, make_request_body, make_hash,
    compute_x_verify_for_endpoint, compute_qr_expiry,
)
from app.core.config import settings
from app.db.models.order import Order, PaymentStatus, KdsStatus
from app.core.dependencies import get_http_client, get_redis_client
from app.db.postgres import get_db

from app.db.schemas.payment import (
    QRInitiateRequest, QRInitiateResponse, StatusResponse,
)
from app.core.rista_utils import post_order_to_kds

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/init", response_model=QRInitiateResponse)
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

    # 3) Call PhonePe
    try:
        resp = await httpx.AsyncClient().post(
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
        order.payment_method = "QR"  # Track payment method
        if expires_in:
            order.qr_expires_at = compute_qr_expiry(
                datetime.now(timezone.utc), int(expires_in)
            )
        order.payment_status = PaymentStatus.PENDING
        await db.commit()
        await db.refresh(order)

        return QRInitiateResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            qr_string=qr_string,
            expires_at=order.qr_expires_at,
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            f"PhonePe QR Error: {e.response.status_code} - {e.response.text}"
        )
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.json()
        )
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe: {e}")
        raise HTTPException(
            status_code=502, detail="Error connecting to payment provider"
        )


@router.get("/status/{order_id}", response_model=StatusResponse)
async def get_payment_status(
        order_id: str,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client),
):
    # 1) Load order from DB
    stmt = select(Order).where(Order.order_id == order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2) If already final, optionally trigger KDS if NOT_POSTED
    if order.payment_status in (
            PaymentStatus.COMPLETED,
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
    ):
        if (
                order.payment_status == PaymentStatus.COMPLETED
                and order.kds_status == KdsStatus.NOT_POSTED
        ):
            # Try to atomically acquire KDS posting lock
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

            if row:
                # This request owns the posting
                await db.refresh(order)
                kdssuccess, invoice = await post_order_to_kds(
                    order, http_client, redis_client
                )
                if kdssuccess and invoice:
                    order.kds_invoice_id = invoice
                    order.kds_status = KdsStatus.POSTED
                    order.kds_last_error = None
                elif not kdssuccess:
                    order.kds_status = KdsStatus.FAILED
                await db.commit()
                await db.refresh(order)
            else:
                # Someone else (likely webhook) changed kds_status in parallel
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

    # 3) Otherwise, query PhonePe and update DB
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
        message = prov.get("message")

        if code == "PAYMENT_SUCCESS":
            new_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_PENDING", "PENDING"):
            new_status = PaymentStatus.PENDING
        else:
            new_status = PaymentStatus.FAILED

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

        # 4) If now completed, try to acquire KDS lock and post
        if new_status == PaymentStatus.COMPLETED and order.kds_status == KdsStatus.NOT_POSTED:
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

            if row:
                await db.refresh(order)
                kdssuccess, invoice = await post_order_to_kds(
                    order, http_client, redis_client
                )
                if kdssuccess and invoice:
                    order.kds_invoice_id = invoice
                    order.kds_status = KdsStatus.POSTED
                    order.kds_last_error = None
                elif not kdssuccess:
                    order.kds_status = KdsStatus.FAILED
                await db.commit()
                await db.refresh(order)
            else:
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
            f"PhonePe Status Error: {e.response.status_code} - {e.response.text}"
        )
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.json()
        )
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe status: {e}")
        raise HTTPException(
            status_code=502, detail="Error connecting to payment provider"
        )
