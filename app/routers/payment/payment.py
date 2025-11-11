import json
import base64
import logging
from datetime import datetime, timezone
import httpx
from sqlalchemy import select, update
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.phonepe_utils import (
    make_base64, make_request_body, make_hash,
    compute_x_verify_for_endpoint, compute_qr_expiry,
    verify_phonepe_callback_hash,
)
from app.core.config import settings
from app.db.models.order import Order, PaymentStatus
from app.core.dependencies import get_http_client, get_redis_client
from app.db.postgres import get_db

from app.db.schemas.payment import (
    QRInitiateRequest, QRInitiateResponse, StatusResponse,
    EDCInitiateResponse, EDCInitiateRequest, EDCStatusResponse
)
from app.services.payment_service import process_webhook_in_background

logger = logging.getLogger(__name__)
router = APIRouter()


# noinspection PyTypeChecker
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
            order_id=order.order_id, transaction_id=order.order_id,
            qr_string=order.qr_string, expires_at=order.qr_expires_at,
        )

    # 2) Build PhonePe payload
    transaction_id = qr_request.order_id
    request_payload = {
        "amount": qr_request.amount_paise, "expiresIn": 180,
        "merchantId": settings.MERCHANT_ID, "merchantOrderId": transaction_id,
        "storeId": getattr(settings, "STORE_ID", None),
        "terminalId": getattr(settings, "TERMINAL_ID", None),
        "transactionId": transaction_id,
        "message": f"Payment for order {transaction_id}",
    }
    request_payload = {k: v for k, v in request_payload.items() if v is not None}
    base64_payload = make_base64(request_payload)
    endpoint = settings.QR_INIT_ENDPOINT
    x_verify = compute_x_verify_for_endpoint(base64_payload, endpoint, settings.SALT_KEY, settings.SALT_KEY_INDEX)

    headers = {
        "Content-Type": "application/json", "X-VERIFY": x_verify,
        "X-PROVIDER-ID": settings.X_PROVIDER_ID,
        "X-CALLBACK-URL": settings.PHONEPE_CALLBACK_URL, "X-CALL-MODE": "POST",
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
            order_id=order.order_id, transaction_id=transaction_id,
            qr_string=qr_string, expires_at=order.qr_expires_at,
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"PhonePe QR Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.json())
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe: {e}")
        raise HTTPException(status_code=502, detail="Error connecting to payment provider")


@router.post("/edc/init", response_model=EDCInitiateResponse)
async def initiate_edc_payment(
        edc_request: EDCInitiateRequest,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Initiates an EDC payment by pushing request to PhonePe terminal.
    Frontend only needs to provide order_id and amount_paise.
    """
    # 1) Validate order exists
    stmt = select(Order).where(Order.order_id == edc_request.order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status == PaymentStatus.COMPLETED:
        return EDCInitiateResponse(
            order_id=order.order_id,
            transaction_id=order.order_id,
            amount=edc_request.amount_paise,
            message="Payment already completed",
        )

    # 2) Build EDC payload with config defaults
    transaction_id = edc_request.order_id
    request_payload = {
        "merchantId": settings.MERCHANT_ID,
        "storeId": settings.STORE_ID,
        "orderId": edc_request.order_id,
        "transactionId": transaction_id,
        "amount": edc_request.amount_paise,
        "paymentModes": ["CARD", "DQR"],  # Support both card and QR
        "integrationMappingType": "ONE_TO_ONE",
        "terminalId": settings.TERMINAL_ID,
        "timeAllowedForHandoverToTerminalSeconds": 60,
        "autoAccept": False,  # Cashier must confirm on terminal
    }

    # Remove None values
    request_payload = {k: v for k, v in request_payload.items() if v is not None}

    base64_payload = make_base64(request_payload)

    # 3) Compute signature
    endpoint = settings.EDC_ENDPOINT
    x_verify = compute_x_verify_for_endpoint(
        base64_payload, endpoint, settings.SALT_KEY, settings.SALT_KEY_INDEX
    )

    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": x_verify,
        "X-PROVIDER-ID": settings.X_PROVIDER_ID,
        "X-CALLBACK-URL": settings.PHONEPE_CALLBACK_URL,  # Same callback for QR and EDC
        "X-CALL-MODE": "POST",
    }

    url = settings.UAT_BASE_URL + endpoint
    data = make_request_body(base64_payload)

    # 4) Call PhonePe EDC API
    try:
        resp = await http_client.post(url, data=data, headers=headers, timeout=30.0)
        resp.raise_for_status()
        payload = resp.json()

        success = payload.get("success", False)
        code = payload.get("code")
        message = payload.get("message", "")

        if not success or code != "SUCCESS":
            logger.error(f"EDC Init failed: {code} - {message}")
            raise HTTPException(
                status_code=400,
                detail=f"EDC initialization failed: {message}"
            )

        # 5) Persist transaction metadata
        order.provider_code = code
        order.provider_txn_id = transaction_id
        order.provider_resp = payload
        order.payment_status = PaymentStatus.PENDING
        order.payment_method = "EDC"  # Mark as EDC vs QR
        await db.commit()

        logger.info(f"EDC payment pushed to terminal for order {edc_request.order_id}")

        return EDCInitiateResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            amount=edc_request.amount_paise,
            message=message or "Payment request sent to EDC terminal",
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"PhonePe EDC Error: {e.response.status_code} - {e.response.text}")
        try:
            error_detail = e.response.json()
        except:
            error_detail = {"error": e.response.text}
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)

    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe EDC: {e}")
        raise HTTPException(status_code=502, detail="Error connecting to payment provider")

# noinspection PyTypeChecker
@router.post("/webhook/phonepe")
async def handle_phonepe_callback(
        request: Request,
        background_tasks: BackgroundTasks,
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client)
):
    logger.info("Received PhonePe webhook...")

    # --- All this validation is FAST ---
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

    # 3. Add the SLOW work to the background
    background_tasks.add_task(
        process_webhook_in_background,
        merchant_order_id=merchant_order_id,
        code=code,
        payload=payload,
        http_client=http_client,
        redis_client=redis_client
    )

    # 4. IMMEDIATELY return 200 OK
    return {"status": "ok", "message": "Webhook acknowledged"}


# noinspection PyTypeChecker
@router.get("/qr/status/{order_id}", response_model=StatusResponse)
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
            order_id=order.order_id, payment_status=order.payment_status,
            provider_code=order.provider_code, provider_raw=order.provider_resp,
        )

    # 2) Otherwise, query PhonePe and update DB
    endpoint = f"{settings.TRANSACTION_ENDPOINT}/{settings.MERCHANT_ID}/{order_id}/status"
    x_verify = make_hash(endpoint + settings.SALT_KEY) + f"###{settings.SALT_KEY_INDEX}"
    headers = {
        "Content-Type": "application/json", "X-VERIFY": x_verify,
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
            update(Order).where(Order.id == order.id).values(
                payment_status=new_status, provider_code=code, provider_resp=prov,
            )
        )
        await db.commit()

        return StatusResponse(
            order_id=order.order_id, payment_status=new_status,
            provider_code=code, provider_message=message, provider_raw=prov,
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"PhonePe Status Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.json())
    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe status: {e}")
        raise HTTPException(status_code=502, detail="Error connecting to payment provider")




@router.get("/edc/status/{transaction_id}", response_model=EDCStatusResponse)
async def check_edc_payment_status(
        transaction_id: str,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Check EDC payment status.
    First checks local DB, then queries PhonePe if status is not final.

    EDC StatusCheck API endpoint:
    GET /v1/edc/transaction/{merchantId}/{transactionId}/status
    """

    # 1) Check database first
    stmt = select(Order).where(Order.order_id == transaction_id)
    order = (await db.execute(stmt)).scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # If status is final, return from DB
    if order.payment_status in (PaymentStatus.COMPLETED, PaymentStatus.FAILED, PaymentStatus.REFUNDED):
        provider_resp = order.provider_resp or {}
        data_node = provider_resp.get("data", {})

        return EDCStatusResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            payment_status=order.payment_status,
            provider_code=order.provider_code,
            payment_mode=data_node.get("paymentMode"),
            reference_number=data_node.get("referenceNumber") or order.provider_reference_id,
            amount=data_node.get("amount"),
            payment_state=data_node.get("paymentState"),
            provider_raw=order.provider_resp,
        )

    # 2) Query PhonePe EDC StatusCheck API for pending transactions
    endpoint = f"/v1/edc/transaction/{settings.MERCHANT_ID}/{transaction_id}/status"
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

        success = prov.get("success", False)
        code = prov.get("code")
        message = prov.get("message", "")
        data_node = prov.get("data", {}) or {}

        # Map PhonePe response code to internal status
        if code == "PAYMENT_SUCCESS":
            new_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED"):
            new_status = PaymentStatus.FAILED
        elif code in ("PAYMENT_PENDING", "PENDING"):
            new_status = PaymentStatus.PENDING
        else:
            # Handle other codes like TRANSACTION_NOT_FOUND, etc.
            new_status = PaymentStatus.PENDING

        # Extract payment details
        payment_modes = data_node.get("paymentModes", [])
        payment_mode = payment_modes[0].get("mode") if payment_modes else None
        reference_number = data_node.get("referenceNumber")

        # Update database with latest status
        await db.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(
                payment_status=new_status,
                provider_code=code,
                provider_resp=prov,
                provider_reference_id=reference_number,
            )
        )
        await db.commit()

        logger.info(f"EDC status check: {transaction_id} -> {code}")

        return EDCStatusResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            payment_status=new_status,
            provider_code=code,
            payment_mode=payment_mode,
            reference_number=reference_number,
            amount=data_node.get("amount"),
            payment_state=data_node.get("paymentState"),
            provider_raw=prov,
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"EDC Status Error: {e.response.status_code} - {e.response.text}")

        # Handle specific error codes
        try:
            error_response = e.response.json()
            error_code = error_response.get("code")

            if error_code == "TRANSACTION_NOT_FOUND":
                # Transaction not found in PhonePe, return current DB status
                return EDCStatusResponse(
                    order_id=order.order_id,
                    transaction_id=transaction_id,
                    payment_status=order.payment_status,
                    provider_code="TRANSACTION_NOT_FOUND",
                    provider_raw=error_response,
                )
            else:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=error_response
                )
        except:
            raise HTTPException(
                status_code=e.response.status_code,
                detail={"error": e.response.text}
            )

    except httpx.RequestError as e:
        logger.error(f"Network error calling EDC status: {e}")
        raise HTTPException(
            status_code=502,
            detail="Error connecting to payment provider"
        )
