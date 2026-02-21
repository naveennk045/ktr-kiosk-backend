from datetime import datetime, timezone
from typing import Any, Dict

from app.core.config import settings
from app.db.models.order import Order, OrderType
from app.utils.tax_utils import money, find_item, build_sale_item


class PetpoojaPayloadBuilder:
    """
    Builds the Petpooja JSON orderinfo payload from an Order and its catalog.

    Fixes applied:
    1. Timestamp alignment: preorder_date/time matches created_on for immediate orders.
    2. Per-unit pricing: final_price is per unit, not total quantity.
    3. Per-unit taxes: item_tax amounts are per unit, not total quantity.
    4. Tax aggregation: Global Tax.details contains total amounts across all items.
    """

    def __init__(self, order: Order, catalog: Dict):
        self.order = order
        self.catalog = catalog

    def build(self) -> Dict[str, Any]:
        catalog_items = self.catalog.get("items", [])
        tax_index = {t["taxTypeId"]: t for t in self.catalog.get("taxTypes", [])}

        order_items, tax_aggregation = self._build_order_items(catalog_items, tax_index)
        final_global_taxes = self._format_global_taxes(tax_aggregation)

        # FIX #1: Use consistent timestamp for immediate orders.
        # When advanced_order = "N", preorder_date/time must match created_on.
        order_timestamp = self.order.created_at if self.order.created_at else datetime.now(timezone.utc)
        preorder_dt = order_timestamp
        advanced_order_flag = "N"

        return {
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
                            "orderID": self.order.order_id,

                            # FIX #1: Aligned timestamps for immediate orders
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
                            "dc_gst_details": [],

                            # Packing charges
                            "packing_charges": "0",
                            "pc_tax_amount": "0",
                            "pc_tax_percentage": "0",
                            "pc_gst_details": [],

                            # Order metadata
                            "order_type": "D" if self.order.order_type == OrderType.DINEIN else "P",
                            "ondc_bap": "",
                            "urgent_order": False,
                            "urgent_time": 20,
                            "payment_type": "COD" if self.order.payment_method == "CASH" else "Online",
                            "table_no": "",
                            "no_of_persons": "0",

                            # Totals
                            "discount_total": "0",
                            "tax_total": str(sum(float(t["tax"]) for t in final_global_taxes)),
                            "discount_type": "F",
                            "total": str(self.order.total_amount_include_tax),

                            # Additional fields
                            "description": "",
                            "enable_delivery": 0,
                            "min_prep_time": 20,
                            "callback_url": settings.PETPOOJA_CALLBACK_URL,
                            "collect_cash": str(self.order.total_amount_include_tax) if self.order.payment_method == "CASH" else "0",
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

    def _build_order_items(self, catalog_items: list, tax_index: dict) -> tuple[list, dict]:
        """
        Builds the list of Petpooja order items and accumulates global tax totals.
        Returns (order_items, tax_aggregation).
        """
        order_items = []
        tax_aggregation: Dict[str, Any] = {}

        for item_spec in self.order.items:
            src_item = find_item(catalog_items, item_spec.get("sku_code"))
            if not src_item:
                raise ValueError(f"SKU {item_spec.get('sku_code')} not found in catalog")

            quantity = item_spec["quantity"]

            # build_sale_item returns total amounts for the quantity
            line, _tax_inc, _tax_exc = build_sale_item(src_item, quantity, tax_index)

            # FIX #2: Petpooja expects per-unit pricing, not totals
            unit_price = float(src_item.get("price"))
            item_discount_per_unit = 0.0  # TODO: Implement discounts if needed
            unit_final_price = unit_price - item_discount_per_unit

            # FIX #3: Calculate per-unit tax amounts
            p_item_taxes = []
            for t in line.get("taxes", []):
                total_tax_amount = float(t.get("amount", 0))
                per_unit_tax = total_tax_amount / quantity

                p_item_taxes.append({
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "tax_percentage": str(t.get("percentage")),
                    "amount": str(round(per_unit_tax, 2))  # Per unit
                })

                # FIX #4: Accumulate total tax amounts for global Tax section
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
                    tax_aggregation[tax_id]["tax"] += total_tax_amount

            order_items.append({
                "id": str(src_item.get("skuCode")),
                "name": src_item.get("itemName"),
                "tax_inclusive": src_item.get("isPriceIncludesTax", False),
                "gst_liability": "vendor",
                "item_tax": p_item_taxes,
                "item_discount": str(item_discount_per_unit),
                "price": str(unit_price),
                "final_price": str(unit_final_price),
                "quantity": str(quantity),
                "description": "",
                "variation_name": "",
                "variation_id": "",
                "AddonItem": {"details": []}  # TODO: Add addon support if needed
            })

        return order_items, tax_aggregation

    def _format_global_taxes(self, tax_aggregation: dict) -> list:
        """Formats accumulated tax totals into Petpooja's global Tax.details format."""
        result = []
        for tax_data in tax_aggregation.values():
            tax_data["tax"] = money(tax_data["tax"])
            result.append(tax_data)
        return result
