import uuid
import math
import time
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order, PaymentStatus, KdsStatus, OrderType
from app.db.models.kot_counter import KotCounter
from app.db.schemas.order import OrderCreateRequest
from app.services.catalog_service import CatalogService
from app.utils.petpooja import PetpoojaClient
from app.core.config import settings

logger = logging.getLogger(__name__)

class OrderService:
    def __init__(
            self,
            db: AsyncSession,
            catalog_service: CatalogService,
            petpooja_client: PetpoojaClient
    ):
        self.db = db
        self.catalog = catalog_service
        self.petpooja = petpooja_client

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
        Posts the order to Petpooja.
        """
        logger.info(f"Syncing order {order.order_id} to Petpooja...")

        if order.kds_status == KdsStatus.POSTED:
            return True, order.kds_invoice_id

        try:
            catalog = await self.catalog.get_catalog(order.channel)
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

            # The user provided response example didn't show success/failure format for SaveOrder explicitly
            # but usually "1" or true indicates success in Petpooja.
            # Assuming "success": "1" based on fetch menu example.

            if success == "1" or success == 1:
                # Invoice ID might be in "poll_id" or "order_id" in response?
                # User example didn't show response body for saveorder.
                # Usually it returns the orderID we sent or an internal ID.
                # We'll use our order_id as reference if not provided.
                server_order_id = response.get("restID") # Just guessing
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

    def _construct_petpooja_payload(self, order: Order, catalog: Dict) -> Dict[str, Any]:
        """Helper to build the Petpooja JSON payload."""
        catalog_items = catalog.get("items", [])
        tax_index = {t["taxTypeId"]: t for t in catalog.get("taxTypes", [])}

        order_items = []
        global_taxes = {} # To collect unique taxes for "Tax" section

        # Calculate Taxes & Items
        for item_spec in order.items:
            src_item = self.catalog.find_item(catalog_items, item_spec.get("sku_code"))
            if not src_item:
                # If item not found (maybe inactive?), we might fail or continue.
                # Raising error to be safe.
                raise ValueError(f"SKU {item_spec.get('sku_code')} not found in catalog")

            line, tax_inc, tax_exc = self.catalog.build_sale_item(
                src_item, item_spec["quantity"], tax_index
            )

            # Transform line -> Petpooja Item
            # taxes list from build_sale_item: [{id, name, percentage, amount, ...}]
            p_item_taxes = []
            for t in line.get("taxes", []):
                p_item_taxes.append({
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "tax_percentage": str(t.get("percentage")),
                    "amount": str(t.get("amount"))
                })
                # Add to global tax list
                if t.get("id"):
                    global_taxes[t.get("id")] = {
                        "id": t.get("id"),
                        "title": t.get("name"),
                        "type": "P", # Percentage
                        "price": str(t.get("percentage")),
                        "tax": str(t.get("amount")), # This acts like an accumulator?
                        # Wait, "tax" in global Tax section usually aggregates?
                        # User example shows "tax": "5.9".
                        # For now, let's just register the definition.
                        # Aggregation might be needed if "Tax" section requires TOTAL tax amount per tax ID.
                    }

            p_item = {
                "id": str(src_item.get("skuCode")),
                "name": src_item.get("itemName"),
                "tax_inclusive": src_item.get("isPriceIncludesTax", False),
                "gst_liability": "vendor", # Hardcoded default
                "item_tax": p_item_taxes,
                "item_discount": "0", # TODO: Handle discounts if any
                "price": str(src_item.get("price")),
                "final_price": str(line.get("itemTotalAmount")),
                "quantity": str(item_spec["quantity"]),
                "description": "",
                "variation_name": "", # Handled if we use variation SKU directly?
                "variation_id": "",
                "AddonItem": { "details": [] } # TODO: add addons support
            }
            order_items.append(p_item)

        # Aggregate Global Taxes
        # We need to sum up tax amounts for the "Tax" section
        final_global_taxes = []
        # Re-iterate items to sum up taxes
        tax_agg = {}
        for p_item in order_items:
            for t in p_item["item_tax"]:
                tid = t["id"]
                if tid not in tax_agg:
                    tax_agg[tid] = {
                        "id": tid,
                        "title": t["name"],
                        "type": "P",
                        "price": t["tax_percentage"],
                        "tax": 0.0,
                        "restaurant_liable_amt": "0.00"
                    }
                tax_agg[tid]["tax"] += float(t["amount"])

        for v in tax_agg.values():
            v["tax"] = self.catalog.money(v["tax"])
            final_global_taxes.append(v)


        # Construct Final Payload
        iso_created = order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            "orderinfo": {
                "OrderInfo": {
                    "Restaurant": {
                        "details": {
                            "res_name": settings.APP_NAME, # Placeholder
                            "address": "Restaurant Address", # Placeholder
                            "contact_information": "9999999999", # Placeholder
                            "restID": settings.PETPOOJA_RESTAURANT_ID
                        }
                    },
                    "Customer": {
                        "details": {
                            "email": "guest@example.com",
                            "name": "Guest",
                            "address": "",
                            "phone": "9999999999",
                            "latitude": "",
                            "longitude": ""
                        }
                    },
                    "Order": {
                        "details": {
                            "orderID": order.order_id,
                            "preorder_date": datetime.now().strftime("%Y-%m-%d"),
                            "preorder_time": datetime.now().strftime("%H:%M:%S"),
                            "service_charge": "0",
                            "sc_tax_amount": "0",
                            "delivery_charges": "0",
                            "dc_tax_percentage": "0",
                            "dc_tax_amount": "0",
                            "packing_charges": "0",
                            "pc_tax_amount": "0",
                            "pc_tax_percentage": "0",
                            "order_type": "D" if order.order_type == OrderType.DINEIN else "P", # Mapping DINEIN->D, TAKEAWAY->P
                            "ondc_bap": "",
                            "advanced_order": "N",
                            "urgent_order": False,
                            "urgent_time": 20,
                            "payment_type": "COD" if order.payment_method == "CASH" else "Online", # Simple mapping
                            "table_no": "",
                            "no_of_persons": "0",
                            "discount_total": "0",
                            "tax_total": str(sum(float(t["tax"]) for t in final_global_taxes)),
                            "discount_type": "F",
                            "total": str(order.total_amount_include_tax),
                            "description": "",
                            "created_on": iso_created,
                            "enable_delivery": 0,
                            "min_prep_time": 20,
                            "callback_url": settings.PETPOOJA_CALLBACK_URL,
                            "collect_cash": str(order.total_amount_include_tax) if order.payment_method == "CASH" else "0",
                            "otp": ""
                        }
                    },
                    "OrderItem": {
                        "details": order_items
                    },
                    "Tax": {
                        "details": final_global_taxes
                    },
                    "Discount": {
                        "details": []
                    }
                }
            }
        }
        return payload

    async def _update_kds_status(self, order: Order, status: KdsStatus, error: str = None, invoice_id: str = None):
        order.kds_status = status
        order.kds_last_attempt_at = datetime.now(timezone.utc)
        if error: order.kds_last_error = error
        if invoice_id: order.kds_invoice_id = invoice_id
        await self.db.commit()
        await self.db.refresh(order)
