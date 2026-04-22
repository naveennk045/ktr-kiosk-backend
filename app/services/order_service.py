import uuid
import math
import logging
from datetime import date, datetime, timezone
from typing import Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import (
    Order,
    OrderItem,
    OrderItemStatus,
    OrderType,
    PaymentStatus,
    KdsStatus,
)
from app.db.models.kot_counter import KotCounter
from app.db.models.store import Store
from app.db.schemas.order import OrderCreateRequest
from app.services.catalog_service import CatalogService
from app.services.petpooja_payload_builder import PetpoojaPayloadBuilder
from app.utils.petpooja import PetpoojaClient, PetpoojaCredentials
from app.utils.takeaway_charges import compute_takeaway_charges

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(
            self,
            db: AsyncSession,
            catalog_service: CatalogService,
            petpooja_client: PetpoojaClient,
            store: Store,
            petpooja_creds: PetpoojaCredentials,
    ):
        self.db = db
        self.catalog = catalog_service
        self.petpooja = petpooja_client
        self.store = store
        self.petpooja_creds = petpooja_creds

    # --- 1. Order Creation Logic ---
    async def create_order(self, request: OrderCreateRequest) -> Order:
        """
        Orchestrates order creation: Fetch Catalog -> Calculate Totals -> Generate KOT -> Save DB
        """
        # 1. Fetch & Validate Catalog
        catalog_data = await self.catalog.get_catalog(request.channel, self.db)
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
            
            # Resolve base price OR variation price
            unit_price = float(catalog_item.get("price", 0.0))
            if item_req.variation_id:
                for var in catalog_item.get("variation", []):
                    if str(var.get("id")) == str(item_req.variation_id):
                        unit_price = float(var.get("price", 0.0))
                        break

            # Resolve addon prices
            addon_price_total = 0.0
            addon_items_list = []
            if item_req.addon_items:
                # Need an index to find the price of the addon item
                addon_index = {
                    str(item["addonitemid"]): float(item.get("addonitem_price", 0.0))
                    for ag in catalog_data.get("addongroups", [])
                    for item in ag.get("addongroupitems", [])
                }
                
                for addon in item_req.addon_items:
                    addon_items_list.append(addon.model_dump())
                    price = addon_index.get(str(addon.addon_item_id), 0.0)
                    addon_price_total += price * addon.quantity

            # The full unit price for KTR internal database includes base + addons
            full_unit_price = unit_price + addon_price_total
            line_total_price = full_unit_price * quantity

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
                # We save final calculated unit price for the DB
                "unit_price": full_unit_price,
                "variation_id": item_req.variation_id,
                "addon_items": addon_items_list,
            })

        qty_sum = sum(line.quantity for line in request.items)

        if request.order_type == OrderType.DINEIN:
            if abs(request.takeaway_charges_without_tax) > 0.01 or abs(
                request.takeaway_charges_with_tax
            ) > 0.01:
                raise ValueError(
                    "For DINEIN, takeaway_charges_without_tax and takeaway_charges_with_tax must be 0"
                )
            tw_exc, tw_inc = 0.0, 0.0
        else:
            tw_exc, tw_inc = compute_takeaway_charges(qty_sum)
            client_sent = (
                abs(request.takeaway_charges_without_tax) > 0.01
                or abs(request.takeaway_charges_with_tax) > 0.01
            )
            if client_sent:
                if abs(request.takeaway_charges_without_tax - tw_exc) > 0.05 or abs(
                    request.takeaway_charges_with_tax - tw_inc
                ) > 0.05:
                    raise ValueError(
                        "Takeaway charges must match server calculation: "
                        f"takeaway_charges_without_tax={tw_exc:.2f}, "
                        f"takeaway_charges_with_tax={tw_inc:.2f}"
                    )

        backend_total_exc += tw_exc
        backend_total_inc += tw_inc

        # 3. Generate IDs
        full_uuid = str(uuid.uuid4()).upper()
        order_id = f"KTR-{full_uuid[0:8]}{full_uuid[10:12]}"
        kot_date, kot_number, kot_code = await self._generate_next_kot()

        # 4. Create order header (lines live in `order_items`)
        new_order = Order(
            store_id=self.store.id,
            order_id=order_id,
            channel=request.channel,
            order_type=request.order_type,
            items=[],
            total_amount_exclude_tax=math.ceil(backend_total_exc),
            total_amount_include_tax=math.ceil(backend_total_inc),
            takeaway_charges_exclude_tax=tw_exc,
            takeaway_charges_include_tax=tw_inc,
            kot_date=kot_date,
            kot_number=kot_number,
            kot_code=kot_code,
            payment_status=PaymentStatus.PENDING,
            kds_status=KdsStatus.NOT_POSTED,
        )

        self.db.add(new_order)
        await self.db.flush()

        for spec in items_for_db:
            self.db.add(
                OrderItem(
                    order_id=new_order.id,
                    item_skuid=spec["sku_code"],
                    item_name=(spec.get("item_name") or "")[:512],
                    quantity=int(spec["quantity"]),
                    price=spec["unit_price"],
                    variation_id=spec.get("variation_id"),
                    addon_items=spec.get("addon_items") or [],
                    order_status=OrderItemStatus.NOT_ACCEPTED,
                )
            )

        await self.db.commit()
        await self.db.refresh(new_order)
        return new_order

    async def _generate_next_kot(self) -> tuple[date, int, str]:
        today = date.today()
        stmt = (
            select(KotCounter)
            .where(KotCounter.store_id == self.store.id, KotCounter.kot_date == today)
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        counter = result.scalar_one_or_none()

        if counter is None:
            counter = KotCounter(store_id=self.store.id, kot_date=today, last_number=0)
            self.db.add(counter)
            await self.db.flush()

        counter.last_number += 1
        return today, counter.last_number, f"KTR-{counter.last_number}"

    # --- 2. KDS Posting Logic ---
    async def sync_order_to_kds(self, order: Order) -> tuple[bool, str | None]:
        """
        Posts the order to Petpooja.
        """
        stmt = (
            select(Order)
            .options(selectinload(Order.line_items))
            .where(Order.id == order.id)
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if not row:
            logger.error("sync_order_to_kds: order id=%s not found", getattr(order, "id", None))
            return False, None
        order = row

        logger.info(f"Syncing order {order.order_id} to Petpooja...")

        if order.kds_status == KdsStatus.POSTED:
            return True, order.kds_invoice_id

        try:
            catalog = await self.catalog.get_catalog(order.channel, self.db)
        except Exception as e:
            await self._update_kds_status(order, KdsStatus.FAILED, f"Catalog error: {e}")
            return False, None

        try:
            payload = self._construct_petpooja_payload(order, catalog)
        except Exception as e:
            await self._update_kds_status(order, KdsStatus.FAILED, f"Payload build error: {e}")
            return False, None

        order.kds_last_attempt_at = datetime.now(timezone.utc)
        order.kds_status = KdsStatus.PENDING
        await self.db.commit()

        try:
            response = await self.petpooja.save_order(payload)
            success = response.get("success")
            message = response.get("message")

            # Petpooja returns "success": "1" for successful orders
            if success == "1" or success == 1:
                # Extract the server-side order ID from response
                # Petpooja typically returns the order ID in the response
                server_order_id = response.get("orderID") or response.get("order_id") or order.order_id
                await self._update_kds_status(order, KdsStatus.POSTED, None, server_order_id)
                logger.info(f"✅ Petpooja Post Success: {order.order_id} - Response: {response}")
                return True, server_order_id
            else:
                error_msg = message or "Unknown error"
                await self._update_kds_status(order, KdsStatus.FAILED, error_msg)
                logger.error(f"Petpooja Post Failed: {error_msg} - Response: {response}")
                return False, None

        except Exception as e:
            await self._update_kds_status(order, KdsStatus.FAILED, str(e))
            logger.error(f"Petpooja Post Exception: {e}")
            return False, None

    def _construct_petpooja_payload(self, order: Order, catalog: Dict) -> Dict:
        """
        Delegates payload construction to PetpoojaPayloadBuilder.
        CatalogService is already injected and uses Redis caching, so re-use is efficient.
        """
        return PetpoojaPayloadBuilder(
            order,
            catalog,
            menu_sharing_code=self.petpooja_creds.menu_sharing_code,
            callback_url=self.petpooja_creds.callback_url,
            res_name=self.store.store_name,
        ).build()

    async def _update_kds_status(self, order: Order, status: KdsStatus, error: str = None, invoice_id: str = None):
        """Update order KDS status and related fields."""
        order.kds_status = status
        order.kds_last_attempt_at = datetime.now(timezone.utc)
        if error:
            order.kds_last_error = error
        if invoice_id:
            order.kds_invoice_id = invoice_id
        await self.db.commit()
        await self.db.refresh(order)
