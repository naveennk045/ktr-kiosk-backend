import uuid
import math
import time
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order, PaymentStatus, KdsStatus
from app.db.models.kot_counter import KotCounter
from app.db.schemas.order import OrderCreateRequest
from app.services.catalog_service import CatalogService
from app.utils.rista import RistaClient
from app.core.config import settings

logger = logging.getLogger(__name__)

class OrderService:
    def __init__(
            self,
            db: AsyncSession,
            catalog_service: CatalogService,
            rista_client: RistaClient
    ):
        self.db = db
        self.catalog = catalog_service
        self.rista = rista_client

    # --- 1. Order Creation Logic ---
    async def create_order(self, request: OrderCreateRequest) -> Order:
        """
        Orchestrates order creation: Fetch Catalog -> Calculate Totals -> Generate KOT -> Save DB
        """
        # 1. Fetch & Validate Catalog
        catalog_data = await self.catalog.get_catalog(request.channel)
        sku_map = {item["skuCode"]: item for item in catalog_data.get("items", [])}
        tax_map = {t["taxTypeId"]: float(t["percentage"]) for t in catalog_data.get("taxTypes", [])}

        # 2. Recalculate Totals
        backend_total_exc = 0.0
        backend_total_inc = 0.0
        items_for_db = []

        for item_req in request.items:
            catalog_item = sku_map.get(item_req.sku_code)
            if not catalog_item:
                raise ValueError(f"Invalid item SKU code: {item_req.sku_code}")

            quantity = item_req.quantity
            unit_price = float(catalog_item.get("price", 0.0))
            line_total_price = unit_price * quantity

            line_tax = 0.0
            if not catalog_item.get("isPriceIncludesTax", False):
                for tax_id in catalog_item.get("taxTypeIds", []):
                    tax_pct = tax_map.get(tax_id, 0.0)
                    line_tax += line_total_price * (tax_pct / 100.0)

            backend_total_exc += line_total_price
            backend_total_inc += line_total_price + line_tax

            items_for_db.append({
                "sku_code": item_req.sku_code,
                "item_name": catalog_item.get("itemName"),
                "quantity": quantity,
                "unit_price": unit_price,
            })

        # 3. Generate IDs
        full_uuid = str(uuid.uuid4()).upper()
        order_id = f"KTR-{full_uuid[0:8]}{full_uuid[10:12]}"
        kot_date, kot_number, kot_code = await self._generate_next_kot()

        # 4. Create Order Object
        new_order = Order(
            order_id=order_id,
            channel=request.channel,
            order_type=request.order_type,
            items=items_for_db,
            total_amount_exclude_tax=math.ceil(backend_total_exc),
            total_amount_include_tax=math.ceil(backend_total_inc),
            kot_date=kot_date,
            kot_number=kot_number,
            kot_code=kot_code,
            payment_status=PaymentStatus.PENDING,
            kds_status=KdsStatus.NOT_POSTED,
        )

        self.db.add(new_order)
        await self.db.commit()
        await self.db.refresh(new_order)
        return new_order

    async def _generate_next_kot(self) -> tuple[date, int, str]:
        today = date.today()
        stmt = select(KotCounter).where(KotCounter.kot_date == today).with_for_update()
        result = await self.db.execute(stmt)
        counter = result.scalar_one_or_none()

        if counter is None:
            counter = KotCounter(kot_date=today, last_number=0)
            self.db.add(counter)
            await self.db.flush()

        counter.last_number += 1
        return today, counter.last_number, f"KTR-{counter.last_number}"

    # --- 2. KDS Posting Logic ---
    async def sync_order_to_kds(self, order: Order) -> tuple[bool, str | None]:
        """
        Posts the order to Rista KDS. Handles idempotency and 409 conflicts.
        """
        logger.info(f"Syncing order {order.order_id} to KDS...")

        if order.kds_status == KdsStatus.POSTED and order.kds_invoice_id:
            return True, order.kds_invoice_id

        try:
            catalog = await self.catalog.get_catalog(order.channel)
        except Exception as e:
            await self._update_kds_status(order, KdsStatus.FAILED, f"Catalog error: {e}")
            return False, None

        try:
            sale_payload = self._construct_kds_payload(order, catalog)
        except Exception as e:
            await self._update_kds_status(order, KdsStatus.FAILED, f"Payload build error: {e}")
            return False, None

        order.kds_last_attempt_at = datetime.now(timezone.utc)
        order.kds_status = KdsStatus.PENDING
        await self.db.commit()

        try:
            request_id = f"kds_{order.order_id}_{int(time.time() * 1000)}"
            response = await self.rista.post_sale(sale_payload, request_id)
            invoice_id = response.get("invoiceNumber")

            await self._update_kds_status(order, KdsStatus.POSTED, None, invoice_id)
            logger.info(f"✅ KDS Post Success: {order.order_id} -> Invoice: {invoice_id}")
            return True, invoice_id

        except Exception as e:
            is_conflict = "409" in str(e) or (hasattr(e, "response") and e.response.status_code == 409)

            if is_conflict:
                logger.warning(f"Conflict for {order.order_id}, checking KDS status...")
                invoice_id = await self.rista.get_sale_status(order.order_id)
                if invoice_id:
                    await self._update_kds_status(order, KdsStatus.POSTED, None, invoice_id)
                    return True, invoice_id

            await self._update_kds_status(order, KdsStatus.FAILED, str(e))
            logger.error(f"KDS Post Failed: {e}")
            return False, None

    def _construct_kds_payload(self, order: Order, catalog: Dict) -> Dict[str, Any]:
        """Helper to build the massive Rista JSON payload."""
        catalog_items = catalog.get("items", [])
        tax_index = {t["taxTypeId"]: t for t in catalog.get("taxTypes", [])}

        sale_items = []
        sum_item_total = 0.0
        sum_tax_inc = 0.0
        sum_tax_exc = 0.0

        for item_spec in order.items:
            src_item = self.catalog.find_item(catalog_items, item_spec.get("sku_code"))
            if not src_item:
                raise ValueError(f"SKU {item_spec.get('sku_code')} not found in catalog")

            line, tax_inc, tax_exc = self.catalog.build_sale_item(
                src_item, item_spec["quantity"], tax_index
            )
            sale_items.append(line)
            sum_item_total += float(line["itemTotalAmount"])
            sum_tax_inc += float(tax_inc)
            sum_tax_exc += float(tax_exc)

        sale_body = {
            "branchCode": settings.BRANCH_CODE,
            "channel": order.channel,
            "status": "Closed",
            "sourceInfo": {
                "source": order.channel,
                "orderTransactionId": order.order_id,
                "invoiceNumber": order.kot_code,
                "invoiceDate": datetime.now(timezone.utc).isoformat(),
            },
            "items": sale_items,
            "itemTotalAmount": self.catalog.money(sum_item_total),
            "payments": [
                {
                    "mode": order.payment_method or "Digital",
                    "amount": self.catalog.money(order.total_amount_include_tax),
                    "reference": order.provider_txn_id or order.order_id,
                    "postedDate": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }

        if sum_tax_inc: sale_body["taxAmountIncluded"] = self.catalog.money(sum_tax_inc)
        if sum_tax_exc: sale_body["taxAmountExcluded"] = self.catalog.money(sum_tax_exc)

        bill_amount = sum_item_total + sum_tax_exc
        sale_body["billAmount"] = self.catalog.money(bill_amount)
        sale_body["roundOffAmount"] = 0.0
        sale_body["billRoundedAmount"] = self.catalog.money(bill_amount)
        sale_body["totalAmount"] = self.catalog.money(order.total_amount_include_tax)

        sale_taxes = self.catalog.summarize_taxes(sale_items)
        if sale_taxes:
            sale_body["taxes"] = sale_taxes

        return sale_body

    async def _update_kds_status(self, order: Order, status: KdsStatus, error: str = None, invoice_id: str = None):
        order.kds_status = status
        if error: order.kds_last_error = error
        if invoice_id: order.kds_invoice_id = invoice_id
        await self.db.commit()
        await self.db.refresh(order)