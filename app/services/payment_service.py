import logging
import httpx
import redis.asyncio as redis
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.core.config import settings
from app.utils.phonepe import (
    make_base64,
    make_hash,
    compute_x_verify_for_endpoint,
    compute_qr_expiry,
)
from app.db.models.order import (
    Order,
    OrderItem,
    OrderItemStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.db.models.cash_pin import CashPin
from app.db.models.store import KioskTerminal, Store, StorePhonePeCredentials
from app.services.order_service import OrderService
from app.services.catalog_service import CatalogService
from app.services.store_cache import (
    get_phonepe_row_cached,
    get_petpooja_credentials_cached,
    get_pinelabs_shared_cached,
)
from app.utils.petpooja import PetpoojaClient
from app.db.session import SessionLocal
from app.kds.notify import emit_kitchen_event

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(
        self,
        db: AsyncSession,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis,
    ):
        self.db = db
        self.http_client = http_client
        self.redis_client = redis_client

    async def _emit_board_refresh_if_newly_completed(
        self, order: Order, prev_status: PaymentStatus
    ) -> None:
        if order.payment_status == PaymentStatus.COMPLETED and prev_status != PaymentStatus.COMPLETED:
            await emit_kitchen_event(
                self.redis_client,
                "BOARD_REFRESH",
                {
                    "reason": "payment_completed",
                    "store_id": order.store_id,
                    "order_id": order.order_id,
                    "kot_code": order.kot_code,
                },
            )

    async def _auto_mark_lines_preparing_if_newly_completed(
        self, order: Order, prev_status: PaymentStatus
    ) -> None:
        """Auto-accept paid orders by moving line items to PREPARING once."""
        if order.payment_status != PaymentStatus.COMPLETED:
            return
        if prev_status == PaymentStatus.COMPLETED:
            return

        await self.db.execute(
            update(OrderItem)
            .where(
                OrderItem.order_id == order.id,
                OrderItem.order_status == OrderItemStatus.NOT_ACCEPTED,
            )
            .values(order_status=OrderItemStatus.PREPARING)
        )
        await self.db.commit()
        await self.db.refresh(order)

    async def _phonepe_for_order(self, order: Order) -> StorePhonePeCredentials:
        row = await get_phonepe_row_cached(self.redis_client, self.db, order.store_id)
        if not row:
            raise HTTPException(
                status_code=503,
                detail="PhonePe credentials not configured for this store",
            )
        return row

    async def _order_service_for_order(self, order: Order) -> OrderService:
        store = await self.db.get(Store, order.store_id)
        if not store:
            raise HTTPException(status_code=500, detail="Order references missing store")
        creds = await get_petpooja_credentials_cached(
            self.redis_client, self.db, order.store_id
        )
        if not creds:
            raise HTTPException(
                status_code=503,
                detail="Petpooja is not configured for this store",
            )
        petpooja = PetpoojaClient(self.http_client, creds)
        catalog = CatalogService(self.redis_client, petpooja, store.id)
        return OrderService(self.db, catalog, petpooja, store, creds)

    # --- QR LOGIC ---
    async def initiate_qr(self, order_id: str, amount_paise: int, terminal_id: Optional[str] = None):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        if order.payment_status == PaymentStatus.PENDING and order.qr_string:
            logger.info(f"Returning existing QR for pending order {order_id}")
            return order

        pp = await self._phonepe_for_order(order)

        request_payload = {
            "amount": amount_paise,
            "expiresIn": 180,
            "merchantId": pp.merchant_id,
            "merchantOrderId": order_id,
            "storeId": pp.phonepe_store_id,
            "terminalId": pp.terminal_id,
            "transactionId": order_id,
            "message": f"Payment for order {order_id}",
        }
        request_payload = {k: v for k, v in request_payload.items() if v is not None}

        base64_payload = make_base64(request_payload)
        endpoint = settings.PHONEPE_QR_INIT_ENDPOINT
        x_verify = compute_x_verify_for_endpoint(
            base64_payload, endpoint, pp.salt_key, pp.salt_key_index
        )

        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": x_verify,
            "X-PROVIDER-ID": pp.x_provider_id,
            "X-CALLBACK-URL": settings.PHONEPE_CALLBACK_URL,
            "X-CALL-MODE": "POST",
        }
        logger.info(headers)
        logger.info(request_payload)

        url = settings.PHONEPE_BASE_URL + endpoint

        try:
            resp = await self.http_client.post(
                url, json={"request": base64_payload}, headers=headers, timeout=30.0
            )
            resp.raise_for_status()
            payload = resp.json()

            data_node = payload.get("data", {}) or {}
            qr_string = (
                data_node.get("qrCode")
                or data_node.get("qrString")
                or data_node.get("instrumentResponse", {}).get("qrData")
            )
            code = payload.get("code")

            order.terminal_id = terminal_id
            order.provider_resp = payload
            order.provider_code = code
            order.qr_string = qr_string
            order.payment_method = PaymentMethod.QR
            order.payment_status = PaymentStatus.PENDING
            order.provider_txn_id = order_id

            expires_in = data_node.get("expiresIn") or 180
            if expires_in:
                order.qr_expires_at = compute_qr_expiry(
                    datetime.now(timezone.utc), int(expires_in)
                )

            await self.db.commit()
            await self.db.refresh(order)
            return order

        except httpx.HTTPStatusError as e:
            logger.error(
                f"QR Init HTTP Error: {e.response.status_code} - {e.response.text}"
            )
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Payment Gateway Error: {e.response.text}",
            )
        except Exception as e:
            logger.error(f"QR Init Failed: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Payment Gateway Error")

    # --- EDC LOGIC (Pine Labs) ---
    async def initiate_edc(self, order_id: str, amount_paise: int, terminal_id: str):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        if order.payment_status == PaymentStatus.PENDING and order.provider_resp:
            logger.info(f"Returning existing EDC request for pending order {order_id}")
            return order

        pl = await get_pinelabs_shared_cached(self.redis_client, self.db, order.store_id)
        if not pl:
            raise HTTPException(
                status_code=503,
                detail="PineLabs credentials not configured for this store",
            )
        kt_stmt = select(KioskTerminal).where(
            KioskTerminal.store_id == order.store_id,
            KioskTerminal.terminal_id == terminal_id,
            KioskTerminal.is_active.is_(True),
        )
        kt = (await self.db.execute(kt_stmt)).scalar_one_or_none()
        if not kt:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No kiosk terminal found for terminal_id '{terminal_id}' "
                    f"for this store."
                ),
            )

        base_url = pl.base_url.rstrip("/")
        url = f"{base_url}/api/CloudBasedIntegration/V1/UploadBilledTransaction"

        try:
            merchant_id = int(pl.merchant_id)
        except ValueError:
            merchant_id = pl.merchant_id

        request_payload = {
            "TransactionNumber": order_id,
            "SequenceNumber": 1,
            "AllowedPaymentMode": "1",
            "ClientID": terminal_id,
            "Amount": str(amount_paise),
            "UserID": pl.user_id,
            "MerchantID": merchant_id,
            "StoreID": kt.pinelabs_store_id,
            "SecurityToken": pl.security_token,
            "AutoCancelDurationInMinutes": 3,
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

            plutus_ref_id = payload.get("PlutusTransactionReferenceID")

            order.terminal_id = terminal_id
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
    async def initiate_cash(self, order_id: str, amount_paise: int, terminal_id: Optional[str] = None, pin: str = ""):
        pin_norm = (pin or "").strip()
        if not pin_norm:
            raise HTTPException(status_code=401, detail="PIN is required for cash payment")

        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        cp_stmt = select(CashPin).where(
            CashPin.store_id == order.store_id,
            CashPin.pin == pin_norm,
        )
        cash_pin = (await self.db.execute(cp_stmt)).scalar_one_or_none()
        if not cash_pin:
            raise HTTPException(status_code=401, detail="Invalid PIN for cash payment")

        if order.payment_status == PaymentStatus.COMPLETED:
            return order

        expected_paise = int(round(float(order.total_amount_include_tax) * 100))
        if amount_paise != expected_paise:
            raise HTTPException(
                status_code=400,
                detail=f"amount_paise must be {expected_paise} (order total in paise)",
            )

        prev_status = order.payment_status
        order.terminal_id = terminal_id
        order.payment_method = PaymentMethod.CASH
        order.payment_status = PaymentStatus.COMPLETED
        order.cash_pin_id = cash_pin.id
        order.cash_collected_by_staff_name = cash_pin.staff_name
        order.provider_txn_id = f"CASH-{order_id}"
        order.provider_code = "SUCCESS"
        order.provider_resp = {
            "message": "Cash payment recorded",
            "staff_name": cash_pin.staff_name,
            "cash_pin_id": cash_pin.id,
        }

        await self.db.commit()
        await self.db.refresh(order)

        await self._auto_mark_lines_preparing_if_newly_completed(order, prev_status)
        await self._emit_board_refresh_if_newly_completed(order, prev_status)
        osvc = await self._order_service_for_order(order)
        await osvc.sync_order_to_kds(order)

        return order

    # --- STATUS CHECK LOGIC (Shared) ---
    async def check_status(self, order_id: str):
        stmt = select(Order).where(Order.order_id == order_id)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_status == PaymentStatus.COMPLETED:
            osvc = await self._order_service_for_order(order)
            await osvc.sync_order_to_kds(order)
            return order

        if order.payment_method == PaymentMethod.CARD:
            return await self._check_pinelabs_status(order)
        return await self._check_phonepe_status(order)

    async def _check_pinelabs_status(self, order: Order):
        pl = await get_pinelabs_shared_cached(self.redis_client, self.db, order.store_id)
        if not pl:
            raise HTTPException(
                status_code=503,
                detail="PineLabs credentials not configured for this store",
            )
        kt_stmt = select(KioskTerminal).where(
            KioskTerminal.store_id == order.store_id,
            KioskTerminal.terminal_id == order.terminal_id,
            KioskTerminal.is_active.is_(True),
        )
        kt = (await self.db.execute(kt_stmt)).scalar_one_or_none()
        if not kt:
            raise HTTPException(
                status_code=404,
                detail=f"No kiosk terminal found for terminal_id '{order.terminal_id}'.",
            )

        base_url = pl.base_url.rstrip("/")
        url = f"{base_url}/api/CloudBasedIntegration/V1/GetCloudBasedTxnStatus"

        try:
            merchant_id = int(pl.merchant_id)
        except ValueError:
            merchant_id = pl.merchant_id

        plutus_ref_id = 0
        if order.provider_reference_id and order.provider_reference_id.isdigit():
            plutus_ref_id = int(order.provider_reference_id)

        payload = {
            "MerchantID": merchant_id,
            "SecurityToken": pl.security_token,
            "StoreID": kt.pinelabs_store_id,
            "ClientID": order.terminal_id,
            "PlutusTransactionReferenceID": plutus_ref_id,
        }

        headers = {"Content-Type": "application/json"}

        try:
            resp = await self.http_client.post(url, json=payload, headers=headers, timeout=50.0)
            data = resp.json()

            logger.info(f"Pine Labs Status Response: {data}")

            response_code = data.get("ResponseCode")

            prev_status = order.payment_status
            new_status = order.payment_status

            if str(response_code) == "0":
                new_status = PaymentStatus.COMPLETED
            elif str(response_code) in ["1001", "1002"]:
                new_status = PaymentStatus.PENDING
            elif str(response_code) != "0" and response_code is not None:
                new_status = PaymentStatus.FAILED

            if new_status != order.payment_status or str(response_code) != str(order.provider_code):
                order.payment_status = new_status
                order.provider_resp = data
                order.provider_code = str(response_code)
                await self.db.commit()

            if new_status == PaymentStatus.COMPLETED:
                await self._auto_mark_lines_preparing_if_newly_completed(order, prev_status)
                await self._emit_board_refresh_if_newly_completed(order, prev_status)
                osvc = await self._order_service_for_order(order)
                await osvc.sync_order_to_kds(order)

            return order

        except Exception as e:
            logger.error(f"Pine Labs Status Check Error: {e}", exc_info=True)
            return order

    async def _check_phonepe_status(self, order: Order):
        pp = await self._phonepe_for_order(order)
        endpoint = f"{settings.PHONEPE_TRANSACTION_ENDPOINT}/{pp.merchant_id}/{order.order_id}/status"

        x_verify = make_hash(endpoint + pp.salt_key) + f"###{pp.salt_key_index}"
        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": x_verify,
            "X-PROVIDER-ID": pp.x_provider_id,
        }
        url = settings.PHONEPE_BASE_URL + endpoint

        try:
            resp = await self.http_client.get(url, headers=headers, timeout=30.0)

            data = resp.json()
            code = data.get("code")

            prev_status = order.payment_status
            new_status = PaymentStatus.PENDING

            if code == "PAYMENT_SUCCESS":
                new_status = PaymentStatus.COMPLETED
            elif code in ["PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED", "TRANSACTION_NOT_FOUND"]:
                new_status = PaymentStatus.FAILED

            if new_status != order.payment_status:
                order.payment_status = new_status
                order.provider_code = code
                order.provider_resp = data
                await self.db.commit()

            if new_status == PaymentStatus.COMPLETED:
                await self._auto_mark_lines_preparing_if_newly_completed(order, prev_status)
                await self._emit_board_refresh_if_newly_completed(order, prev_status)
                osvc = await self._order_service_for_order(order)
                await osvc.sync_order_to_kds(order)

            return order

        except httpx.HTTPStatusError as e:
            logger.error(f"Status Check HTTP Error: {e.response.status_code} - {e.response.text}")
            return order
        except Exception as e:
            logger.error(f"Status Check Error: {e}", exc_info=True)
            return order

    async def handle_webhook(self, merchant_order_id: str, code: str, payload: dict):
        stmt = select(Order).where(Order.order_id == merchant_order_id)
        result = await self.db.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            logger.error(f"Order {merchant_order_id} not found during webhook processing")
            return

        prev_status = order.payment_status
        order.provider_code = code
        order.provider_resp = payload

        if code == "PAYMENT_SUCCESS":
            order.payment_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED"):
            order.payment_status = PaymentStatus.FAILED

        await self.db.commit()
        await self.db.refresh(order)

        if order.payment_status == PaymentStatus.COMPLETED:
            await self._auto_mark_lines_preparing_if_newly_completed(order, prev_status)
            await self._emit_board_refresh_if_newly_completed(order, prev_status)
            osvc = await self._order_service_for_order(order)
            await osvc.sync_order_to_kds(order)

    @staticmethod
    async def run_webhook_in_background(
        merchant_order_id: str,
        code: str,
        payload: dict,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis,
    ):
        logger.info(f"Background webhook task running for order {merchant_order_id}...")

        async with SessionLocal() as db:
            payment_service = PaymentService(db, http_client, redis_client)
            await payment_service.handle_webhook(merchant_order_id, code, payload)
