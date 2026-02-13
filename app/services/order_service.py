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

    def _construct_petpooja_payload(self, order: Order, catalog: Dict) -> Dict[str, Any]:
        """
        Helper to build the Petpooja JSON payload.

        FIXES APPLIED:
        1. ✅ Timestamp alignment: preorder_date/time matches created_on for immediate orders
        2. ✅ Per-unit pricing: final_price is per unit, not total quantity
        3. ✅ Per-unit taxes: item_tax amounts are per unit, not total quantity
        4. ✅ Tax aggregation: Global Tax.details contains total amounts across all items
        """
        catalog_items = catalog.get("items", [])
        tax_index = {t["taxTypeId"]: t for t in catalog.get("taxTypes", [])}

        order_items = []
        tax_aggregation = {}  # To accumulate total tax amounts per tax ID

        # Calculate Taxes & Items
        for item_spec in order.items:
            src_item = self.catalog.find_item(catalog_items, item_spec.get("sku_code"))
            if not src_item:
                raise ValueError(f"SKU {item_spec.get('sku_code')} not found in catalog")

            quantity = item_spec["quantity"]

            # build_sale_item returns total amounts for the quantity
            line, tax_inc, tax_exc = self.catalog.build_sale_item(
                src_item, quantity, tax_index
            )

            # ✅ FIX #2: Calculate per-unit values (Petpooja expects per-unit, not total)
            unit_price = float(src_item.get("price"))
            item_discount_per_unit = 0.0  # TODO: Implement discounts if needed
            unit_final_price = unit_price - item_discount_per_unit

            # ✅ FIX #3: Calculate per-unit tax amounts
            p_item_taxes = []
            for t in line.get("taxes", []):
                # line.taxes contains TOTAL tax for all quantities
                # We need PER-UNIT tax amount for Petpooja
                total_tax_amount = float(t.get("amount", 0))
                per_unit_tax = total_tax_amount / quantity

                p_item_taxes.append({
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "tax_percentage": str(t.get("percentage")),
                    "amount": str(round(per_unit_tax, 2))  # Per unit
                })

                # ✅ FIX #4: Accumulate total tax amounts for global Tax section
                tax_id = t.get("id")
                if tax_id:
                    if tax_id not in tax_aggregation:
                        tax_aggregation[tax_id] = {
                            "id": tax_id,
                            "title": t.get("name"),
                            "type": "P",
                            "price": str(t.get("percentage")),
                            "tax": 0.0,
                            "restaurant_liable_amt": "0.00"
                        }
                    # Add the TOTAL tax amount (for all quantities of this item)
                    tax_aggregation[tax_id]["tax"] += total_tax_amount

            # Build Petpooja item structure
            p_item = {
                "id": str(src_item.get("skuCode")),
                "name": src_item.get("itemName"),
                "tax_inclusive": src_item.get("isPriceIncludesTax", False),
                "gst_liability": "vendor",  # Default; adjust if needed
                "item_tax": p_item_taxes,
                "item_discount": str(item_discount_per_unit),  # Per unit
                "price": str(unit_price),  # Per unit
                "final_price": str(unit_final_price),  # Per unit (price - discount)
                "quantity": str(quantity),
                "description": "",
                "variation_name": "",
                "variation_id": "",
                "AddonItem": {"details": []}  # TODO: Add addon support if needed
            }
            order_items.append(p_item)

        # Format global taxes
        final_global_taxes = []
        for tax_data in tax_aggregation.values():
            # Use catalog.money() to format tax amount consistently
            tax_data["tax"] = self.catalog.money(tax_data["tax"])
            final_global_taxes.append(tax_data)

        # ✅ FIX #1: Use consistent timestamp for immediate orders
        # When advanced_order = "N", preorder_date/time must match created_on
        order_timestamp = order.created_at if order.created_at else datetime.now(timezone.utc)

        # For future: Support scheduled orders by checking order.scheduled_for
        # is_advanced_order = order.scheduled_for is not None
        # preorder_dt = order.scheduled_for if is_advanced_order else order_timestamp
        # advanced_order_flag = "Y" if is_advanced_order else "N"

        # Current implementation: All orders are immediate
        preorder_dt = order_timestamp
        advanced_order_flag = "N"

        payload = {
            "orderinfo": {
                "OrderInfo": {
                    "Restaurant": {
                        "details": {
                            "res_name": settings.APP_NAME,
                            "address": "Restaurant Address",  # TODO: Use actual restaurant address
                            "contact_information": "9999999999",  # TODO: Use actual contact number
                            "restID": settings.PETPOOJA_RESTAURANT_ID
                        }
                    },
                    "Customer": {
                        "details": {
                            "email": "guest@example.com",  # TODO: Use actual customer email if available
                            "name": "Guest",  # TODO: Use actual customer name if available
                            "address": "",
                            "phone": "9999999999",  # TODO: Use actual customer phone if available
                            "latitude": "",
                            "longitude": ""
                        }
                    },
                    "Order": {
                        "details": {
                            "orderID": order.order_id,

                            # ✅ FIXED: Aligned timestamps for immediate orders
                            "preorder_date": preorder_dt.strftime("%Y-%m-%d"),
                            "preorder_time": preorder_dt.strftime("%H:%M:%S"),
                            "created_on": order_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            "advanced_order": advanced_order_flag,

                            # Service charges
                            "service_charge": "0",
                            "sc_tax_amount": "0",

                            # Delivery charges
                            "delivery_charges": "0",
                            "dc_tax_percentage": "0",
                            "dc_tax_amount": "0",
                            "dc_gst_details": [],  # Add if delivery charges have GST

                            # Packing charges
                            "packing_charges": "0",
                            "pc_tax_amount": "0",
                            "pc_tax_percentage": "0",
                            "pc_gst_details": [],  # Add if packing charges have GST

                            # Order metadata
                            "order_type": "D" if order.order_type == OrderType.DINEIN else "P",
                            "ondc_bap": "",
                            "urgent_order": False,
                            "urgent_time": 20,
                            "payment_type": "COD" if order.payment_method == "CASH" else "Online",
                            "table_no": "",
                            "no_of_persons": "0",

                            # Totals
                            "discount_total": "0",
                            "tax_total": str(sum(float(t["tax"]) for t in final_global_taxes)),
                            "discount_type": "F",
                            "total": str(order.total_amount_include_tax),

                            # Additional fields
                            "description": "",
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
                        "details": []  # TODO: Add discount support if needed
                    }
                }
            }
        }

        # Debug: Save payload to file for inspection
        # Uncomment for debugging
        with open("sample_order.json", "w") as f:
            import json
            json.dump(payload, f, indent=4)

        return payload

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