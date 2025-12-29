import logging
import httpx
from sqlalchemy import select, update
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.phonepe_utils import (
    make_base64, make_request_body, make_hash,
    compute_x_verify_for_endpoint
)
from app.core.config import settings
from app.db.models.order import Order, PaymentStatus, KdsStatus
from app.core.dependencies import get_http_client, get_redis_client
from app.db.session import get_db

from app.db.schemas.payment import (
    EDCInitiateResponse, EDCInitiateRequest, EDCStatusResponse
)
from app.core.rista_utils import post_order_to_kds

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/init", response_model=EDCInitiateResponse)
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
        "paymentModes": ["CARD"],
        "integrationMappingType": "ONE_TO_ONE",
        "terminalId": settings.TERMINAL_ID,
        "timeAllowedForHandoverToTerminalSeconds": 60,
        "autoAccept": True,
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
                detail=f"EDC initialization failed: {message}",
            )

        # 5) Persist transaction metadata
        order.provider_code = code
        order.provider_txn_id = transaction_id
        order.provider_resp = payload
        order.payment_status = PaymentStatus.PENDING
        order.payment_method = "EDC"  # Mark as EDC vs QR
        await db.commit()
        await db.refresh(order)

        logger.info(
            f"EDC payment pushed to terminal for order {edc_request.order_id}"
        )

        return EDCInitiateResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            amount=edc_request.amount_paise,
            message=message or "Payment request sent to EDC terminal",
        )

    except httpx.HTTPStatusError as e:
        logger.error(
            f"PhonePe EDC Error: {e.response_status} - {e.response.text}"
        )
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = {"error": e.response.text}
        raise HTTPException(
            status_code=e.response.status_code, detail=error_detail
        )

    except httpx.RequestError as e:
        logger.error(f"Network error calling PhonePe EDC: {e}")
        raise HTTPException(
            status_code=502, detail="Error connecting to payment provider"
        )


@router.get("/status/{transaction_id}", response_model=EDCStatusResponse)
async def check_edc_payment_status(
        transaction_id: str,
        db: AsyncSession = Depends(get_db),
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client),
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

    # If status is final, ensure KDS is posted for COMPLETED
    if order.payment_status in (
            PaymentStatus.COMPLETED,
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
    ):
        if (
                order.payment_status == PaymentStatus.COMPLETED
                and order.kds_status != KdsStatus.POSTED
        ):
            kdssuccess, invoice = await post_order_to_kds(
                order, http_client, redis_client
            )
            if kdssuccess and invoice:
                order.kds_invoice_id = invoice
            await db.commit()
            await db.refresh(order)

        provider_resp = order.provider_resp or {}
        data_node = provider_resp.get("data", {})

        return EDCStatusResponse(
            order_id=order.order_id,
            transaction_id=transaction_id,
            payment_status=order.payment_status,
            provider_code=order.provider_code,
            payment_mode=data_node.get("paymentMode"),
            reference_number=data_node.get("referenceNumber")
                             or order.provider_reference_id,
            amount=data_node.get("amount"),
            payment_state=data_node.get("paymentState"),
            provider_raw=order.provider_resp,
            kds_invoice_id=order.kds_invoice_id,
            kds_status=order.kds_status,
            kot_code=order.kot_code,
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
        provider_status = (data_node.get("status") or "").upper()

        # Only treat as COMPLETED if both outer code and inner data.status == SUCCESS
        is_completed = (
                success and
                code in ("PAYMENT_SUCCESS", "SUCCESS") and
                provider_status == "SUCCESS"
        )

        if is_completed:
            new_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED"):
            new_status = PaymentStatus.FAILED
        elif code in ("PAYMENT_PENDING", "PENDING") or provider_status in ("PENDING", ""):
            new_status = PaymentStatus.PENDING
        else:
            # For safety, treat unknown as pending
            new_status = PaymentStatus.PENDING

        # Extract payment details robustly
        payment_mode = data_node.get("paymentMode")
        reference_number = data_node.get("referenceNumber")

        # Try "paymentInstruments" for more payment info if missing/empty
        if not payment_mode and "paymentInstruments" in data_node:
            instruments = data_node["paymentInstruments"]
            if instruments and isinstance(instruments, list):
                first = instruments[0]
                payment_mode = first.get("type")
        if not reference_number and "paymentInstruments" in data_node:
            instruments = data_node["paymentInstruments"]
            if instruments and isinstance(instruments, list):
                first = instruments[0]
                reference_number = first.get("referenceNumber")

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
        await db.refresh(order)

        # If now completed, ensure KDS is posted
        if new_status == PaymentStatus.COMPLETED and order.kds_status != KdsStatus.POSTED:
            kdssuccess, invoice = await post_order_to_kds(
                order, http_client, redis_client
            )
            if kdssuccess and invoice:
                order.kds_invoice_id = invoice
            await db.commit()
            await db.refresh(order)

        logger.info(f"EDC status check: {transaction_id} -> code={code}, status={provider_status}, db={new_status}")

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
            kds_invoice_id=order.kds_invoice_id,
            kds_status=order.kds_status,
            kot_code=order.kot_code,
        )

    except httpx.HTTPStatusError as e:
        logger.error(
            f"EDC Status Error: {e.response.status_code} - {e.response.text}"
        )
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
                    kds_invoice_id=order.kds_invoice_id,
                    kds_status=order.kds_status,
                    kot_code=order.kot_code,
                )
            else:
                raise HTTPException(
                    status_code=e.response.status_code, detail=error_response
                )
        except Exception:
            raise HTTPException(
                status_code=e.response.status_code,
                detail={"error": e.response.text},
            )

    except httpx.RequestError as e:
        logger.error(f"Network error calling EDC status: {e}")
        raise HTTPException(
            status_code=502,
            detail="Error connecting to payment provider",
        )
