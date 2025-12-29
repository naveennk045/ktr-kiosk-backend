import logging
import httpx
import redis.asyncio as redis
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.core.config import settings
from app.utils.phonepe import (
    make_base64, make_hash,
    compute_x_verify_for_endpoint, compute_qr_expiry,
)
from app.db.models.order import Order, PaymentStatus, KdsStatus, PaymentMethod
from app.services.order_service import OrderService
from app.services.catalog_service import CatalogService
from app.utils.rista import RistaClient
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(
            self,
            db: AsyncSession,
            http_client: httpx.AsyncClient,
            redis_client: redis.Redis,
            order_service: OrderService
    ):
        self.db = db
        self.http_client = http_client
        self.redis_client = redis_client
        self.order_service = order_service

    # --- QR LOGIC ---
    async def initiate_qr(self, order_id: str, amount_paise: int):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # 1. Reuse existing
        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        # Return existing QR if pending
        if order.payment_status == PaymentStatus.PENDING and order.qr_string:
            logger.info(f"Returning existing QR for pending order {order_id}")
            return order

        # 2. Build Payload
        request_payload = {
            "amount": amount_paise,
            "expiresIn": 180,
            "merchantId": settings.MERCHANT_ID,
            "merchantOrderId": order_id,
            "storeId": getattr(settings, "STORE_ID", None),
            "terminalId": getattr(settings, "TERMINAL_ID", None),
            "transactionId": order_id,
            "message": f"Payment for order {order_id}",
        }
        request_payload = {k: v for k, v in request_payload.items() if v is not None}

        # 3. Hash & Call
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

        try:
            resp = await self.http_client.post(url, json={"request": base64_payload}, headers=headers, timeout=30.0)
            resp.raise_for_status()
            payload = resp.json()

            data_node = payload.get("data", {}) or {}
            qr_string = data_node.get("qrCode") or data_node.get("qrString") or data_node.get("instrumentResponse", {}).get("qrData")
            code = payload.get("code")

            # 4. Update DB
            order.provider_resp = payload
            order.provider_code = code
            order.qr_string = qr_string
            order.payment_method = PaymentMethod.QR
            order.payment_status = PaymentStatus.PENDING
            order.provider_txn_id = order_id

            expires_in = data_node.get("expiresIn") or 180
            if expires_in:
                order.qr_expires_at = compute_qr_expiry(datetime.now(timezone.utc), int(expires_in))

            await self.db.commit()
            await self.db.refresh(order)
            return order

        except Exception as e:
            logger.error(f"QR Init Failed: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Payment Gateway Error")

    # --- EDC LOGIC ---
    async def initiate_edc(self, order_id: str, amount_paise: int):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        # 2. Build Payload
        # 2. Build Payload
        request_payload = {
            "merchantId": settings.MERCHANT_ID,
            "storeId": settings.STORE_ID,
            "orderId": order_id,
            "transactionId": order_id,
            "amount": amount_paise,
            "paymentModes": ["CARD"],
            "integrationMappingType": "ONE_TO_ONE",
            "terminalId": settings.TERMINAL_ID,
            "timeAllowedForHandoverToTerminalSeconds": 60,
            "autoAccept": True,
        }
        request_payload = {k: v for k, v in request_payload.items() if v is not None}

        # 3. Hash & Call
        base64_payload = make_base64(request_payload)
        endpoint = settings.EDC_ENDPOINT
        x_verify = compute_x_verify_for_endpoint(base64_payload, endpoint, settings.SALT_KEY, settings.SALT_KEY_INDEX)

        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": x_verify,
            "X-PROVIDER-ID": settings.X_PROVIDER_ID,
            "X-CALL-MODE": "POST",
        }
        url = settings.UAT_BASE_URL + endpoint

        try:
            resp = await self.http_client.post(url, json={"request": base64_payload}, headers=headers, timeout=30.0)
            resp.raise_for_status()
            payload = resp.json()

            # 4. Update DB
            order.provider_resp = payload
            order.payment_method = PaymentMethod.CARD
            order.payment_status = PaymentStatus.PENDING
            order.provider_txn_id = order_id

            await self.db.commit()
            await self.db.refresh(order)
            return order
        except Exception as e:
            logger.error(f"EDC Init Failed: {e}")
            raise HTTPException(status_code=502, detail="EDC Error")

    # --- STATUS CHECK LOGIC (Shared) ---
    async def check_status(self, order_id: str):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # 1. If final, try KDS
        if order.payment_status == PaymentStatus.COMPLETED:
            await self.order_service.sync_order_to_kds(order)
            return order

        # 2. Check Provider
        is_edc = (order.payment_method == PaymentMethod.CARD)

        # Endpoint construction
        if is_edc:
            endpoint = f"/v1/edc/transaction/{settings.MERCHANT_ID}/{order_id}/status"
        else:
            endpoint = f"{settings.TRANSACTION_ENDPOINT}/{settings.MERCHANT_ID}/{order_id}/status"

        x_verify = make_hash(endpoint + settings.SALT_KEY) + f"###{settings.SALT_KEY_INDEX}"
        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": x_verify,
            "X-PROVIDER-ID": settings.X_PROVIDER_ID,
        }
        url = settings.UAT_BASE_URL + endpoint

        try:
            resp = await self.http_client.get(url, headers=headers, timeout=30.0)

            data = resp.json()
            code = data.get("code")
            inner_status = data.get("data", {}).get("status", "")
            success = data.get("success", False)

            # 3. Map Status
            new_status = PaymentStatus.PENDING

            if is_edc:
                if code == "SUCCESS" and inner_status == "SUCCESS":
                    new_status = PaymentStatus.COMPLETED
                elif inner_status in ["FAILED", "DECLINED", "CANCELLED"]:
                    new_status = PaymentStatus.FAILED
            else:
                if code == "PAYMENT_SUCCESS":
                    new_status = PaymentStatus.COMPLETED
                elif code in ["PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED", "TRANSACTION_NOT_FOUND"]:
                    new_status = PaymentStatus.FAILED

            # 4. Update DB
            if new_status != order.payment_status:
                order.payment_status = new_status
                order.provider_code = code
                order.provider_resp = data
                await self.db.commit()

            # 5. KDS Sync
            if new_status == PaymentStatus.COMPLETED:
                await self.order_service.sync_order_to_kds(order)

            return order

        except Exception as e:
            logger.error(f"Status Check Error: {e}")
            return order

    async def handle_webhook(self, merchant_order_id: str, code: str, payload: dict):
        """
        Logic for processing webhook notification.
        Supports both background task and direct call.
        """
        stmt = select(Order).where(Order.order_id == merchant_order_id)
        result = await self.db.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            logger.error(f"Order {merchant_order_id} not found during webhook processing")
            return

        order.provider_code = code
        order.provider_resp = payload

        if code == "PAYMENT_SUCCESS":
            order.payment_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED"):
            order.payment_status = PaymentStatus.FAILED

        await self.db.commit()
        await self.db.refresh(order)

        if order.payment_status == PaymentStatus.COMPLETED:
            await self.order_service.sync_order_to_kds(order)


# --- BACKGROUND TASK ---

async def process_webhook_in_background(
        merchant_order_id: str,
        code: str,
        payload: dict,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis,
):
    """
    Independent DB Session for background processing.
    Manually instantiates services.
    """
    logger.info(f"Background webhook task running for order {merchant_order_id}...")

    async with SessionLocal() as db:
        rista_client = RistaClient(http_client)
        catalog_service = CatalogService(redis_client, rista_client)
        order_service = OrderService(db, catalog_service, rista_client)
        payment_service = PaymentService(db, http_client, redis_client, order_service)

        await payment_service.handle_webhook(merchant_order_id, code, payload)
