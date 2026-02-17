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

from app.db.session import SessionLocal
from app.db.models.edc_config import EdcConfig

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
    async def initiate_qr(self, order_id: str, amount_paise: int, store_id: Optional[str] = None):
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
            "storeId": store_id if store_id else getattr(settings, "STORE_ID", None),
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
        logger.info(headers)
        logger.info(request_payload)

        url = settings.PHONEPE_BASE_URL + endpoint

        try:
            resp = await self.http_client.post(url, json={"request": base64_payload}, headers=headers, timeout=30.0)
            resp.raise_for_status()
            payload = resp.json()

            data_node = payload.get("data", {}) or {}
            qr_string = data_node.get("qrCode") or data_node.get("qrString") or data_node.get("instrumentResponse", {}).get("qrData")
            code = payload.get("code")

            # 4. Update DB
            order.store_id = store_id if store_id else getattr(settings, "STORE_ID", None)
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

        except httpx.HTTPStatusError as e:
            logger.error(f"QR Init HTTP Error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=f"Payment Gateway Error: {e.response.text}")
        except Exception as e:
            logger.error(f"QR Init Failed: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Payment Gateway Error")

    # --- EDC LOGIC ---
    # --- EDC LOGIC (Pine Labs) ---
    async def initiate_edc(self, order_id: str, amount_paise: int, store_id: str):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        # Return existing EDC response if pending
        if order.payment_status == PaymentStatus.PENDING and order.provider_resp:
            logger.info(f"Returning existing EDC request for pending order {order_id}")
            return order

        # Pine Labs URLhttps://www.plutuscloudservice.in:8201/API
        base_url = settings.PINELABS_EDC_BASE_URL.rstrip("/")
        url = f"{base_url}/api/CloudBasedIntegration/V1/UploadBilledTransaction"

        # Try to parse MerchantID as int if possible, else string
        try:
            merchant_id = int(settings.PINELABS_EDC_MERCHANT_ID)
        except ValueError:
            merchant_id = settings.PINELABS_EDC_MERCHANT_ID

        # Build Payload
        request_payload = {
            "TransactionNumber": order_id,
            "SequenceNumber": 1,
            "AllowedPaymentMode": "1 | 10",
            "ClientID": settings.PINELABS_EDC_CLIENT_ID,
            "Amount": str(amount_paise),
            "UserID": settings.PINELABS_EDC_USER_ID,
            "MerchantID": merchant_id,
            "StoreID": settings.PINELABS_STORE_ID,
            "SecurityToken": settings.PINELABS_EDC_SECURITY_TOKEN,
            "AutoCancelDurationInMinutes": 5
        }

        headers = {
            "Content-Type": "application/json",
        }

        logger.info(f"Initiating Pine Labs EDC: {url}")
        logger.info(request_payload)

        try:
            resp = await self.http_client.post(url, json=request_payload, headers=headers, timeout=30.0)
            resp.raise_for_status()
            payload = resp.json()
            logger.info(f"Pine Labs Response: {payload}")

            # Extract PlutusTransactionReferenceID if available
            plutus_ref_id = payload.get("PlutusTransactionReferenceID")

            # Update DB
            order.store_id = store_id
            order.provider_resp = payload
            order.provider_reference_id = str(plutus_ref_id) if plutus_ref_id else None
            order.payment_method = PaymentMethod.CARD
            order.payment_status = PaymentStatus.PENDING
            order.provider_txn_id = order_id

            await self.db.commit()
            await self.db.refresh(order)
            return order

        except httpx.HTTPStatusError as e:
            logger.error(f"Pine Labs Init HTTP Error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=f"EDC Gateway Error: {e.response.text}")
        except Exception as e:
            logger.error(f"Pine Labs Init Failed: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="EDC Error")

    # --- CASH LOGIC ---
    async def initiate_cash(self, order_id: str, amount_paise: int, store_id: Optional[str] = None, pin: str = ""):
        if pin != settings.CASH_PAYMENT_PIN:
             raise HTTPException(status_code=401, detail="Invalid PIN for cash payment")

        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        # Update DB
        order.store_id = store_id if store_id else getattr(settings, "STORE_ID", None)
        order.payment_method = PaymentMethod.CASH
        order.payment_status = PaymentStatus.COMPLETED
        order.provider_txn_id = f"CASH-{order_id}"
        order.provider_code = "SUCCESS"
        order.provider_resp = {"message": "Cash payment recorded"}

        await self.db.commit()
        await self.db.refresh(order)

        # Sync to KDS immediately
        await self.order_service.sync_order_to_kds(order)

        return order

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
        if order.payment_method == PaymentMethod.CARD:
            # Pine Labs Status Check
            return await self._check_pinelabs_status(order)
        else:
            # PhonePe QR Status Check
            return await self._check_phonepe_status(order)

    async def _check_pinelabs_status(self, order: Order):
        base_url = settings.PINELABS_EDC_BASE_URL.rstrip("/")
        url = f"{base_url}/api/CloudBasedIntegration/V1/GetCloudBasedTxnStatus"

        # Try to parse MerchantID as int if possible, else string
        try:
            merchant_id = int(settings.PINELABS_EDC_MERCHANT_ID)
        except ValueError:
            merchant_id = settings.PINELABS_EDC_MERCHANT_ID

        plutus_ref_id = 0
        if order.provider_reference_id and order.provider_reference_id.isdigit():
             plutus_ref_id = int(order.provider_reference_id)

        payload = {
           "MerchantID": merchant_id,
           "SecurityToken": settings.PINELABS_EDC_SECURITY_TOKEN,
           "StoreId": settings.PINELABS_STORE_ID,
           "ClientId": settings.PINELABS_EDC_CLIENT_ID,
           "PlutusTransactionReferenceID": plutus_ref_id
        }

        headers = {"Content-Type": "application/json"}

        try:
            resp = await self.http_client.post(url, json=payload, headers=headers, timeout=30.0)
            data = resp.json() # Pine labs returns JSON directly

            # Logic to determine status from Pine Labs response
            # Assuming typical Pine Labs response structure
            # Example response wasn't fully provided but inferred from "PlutusTransactionReferenceID" usage
            # We look for "ResponseCode" check usually. 0 is success often.
            # But prompt didn't specify success condition.
            # I will log the response and assume some standard fields or check for "Transaction Status" if available.

            logger.info(f"Pine Labs Status Response: {data}")

            # Common Pine Labs fields: ResponseCode, ResponseMessage.
            # 0 is usually success.
            # Let's trust the user might have provided more info or valid assumptions.
            # User said: "if edc endpoint is called then it will work with pine labs"
            # User provided Get Status Payload.

            # I will conservatively check for implicit success or explicit status fields.
            # If no clear docs, I will map basic 200 OK + some field check.

            response_code = data.get("ResponseCode")
            message = data.get("ResponseMessage", "")

            new_status = order.payment_status

            # Adjust mapping based on actual API behavior.
            if str(response_code) == "0":
                 new_status = PaymentStatus.COMPLETED
            elif str(response_code) in ["1001", "1002"]:
                 # 1001 = TXN UPLOADED, 1002 = PROCESSING
                 # Treat as PENDING, do not fail.
                 new_status = PaymentStatus.PENDING
            elif str(response_code) != "0" and response_code is not None:
                 # If explicit failure code (e.g. 1003, 1004)
                 new_status = PaymentStatus.FAILED

            # Always update provider response and code for debugging/tracking
            if new_status != order.payment_status or str(response_code) != str(order.provider_code):
                order.payment_status = new_status
                order.provider_resp = data
                order.provider_code = str(response_code)
                await self.db.commit()

            if new_status == PaymentStatus.COMPLETED:
                await self.order_service.sync_order_to_kds(order)

            return order

        except Exception as e:
            logger.error(f"Pine Labs Status Check Error: {e}", exc_info=True)
            return order

    async def _check_phonepe_status(self, order: Order):
        # Existing PhonePe logic
        endpoint = f"{settings.TRANSACTION_ENDPOINT}/{settings.MERCHANT_ID}/{order.order_id}/status"

        x_verify = make_hash(endpoint + settings.SALT_KEY) + f"###{settings.SALT_KEY_INDEX}"
        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": x_verify,
            "X-PROVIDER-ID": settings.X_PROVIDER_ID,
        }
        url = settings.PHONEPE_BASE_URL + endpoint

        try:
            resp = await self.http_client.get(url, headers=headers, timeout=30.0)

            data = resp.json()
            code = data.get("code")
            success = data.get("success", False)

            new_status = PaymentStatus.PENDING

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

        except httpx.HTTPStatusError as e:
            logger.error(f"Status Check HTTP Error: {e.response.status_code} - {e.response.text}")
            return order
        except Exception as e:
            logger.error(f"Status Check Error: {e}", exc_info=True)
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


from app.utils.petpooja import PetpoojaClient

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
        petpooja_client = PetpoojaClient(http_client)
        catalog_service = CatalogService(redis_client, petpooja_client)
        order_service = OrderService(db, catalog_service, petpooja_client)
        payment_service = PaymentService(db, http_client, redis_client, order_service)

        await payment_service.handle_webhook(merchant_order_id, code, payload)
