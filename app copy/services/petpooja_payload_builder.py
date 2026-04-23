from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.models.order import Order, OrderType
from app.utils.tax_utils import money, find_item, build_sale_item


def _order_takeaway_exc_inc(order: Order) -> tuple[float, float]:
    exc = getattr(order, "takeaway_charges_exclude_tax", None)
    inc = getattr(order, "takeaway_charges_include_tax", None)
    if exc is None or inc is None:
        return 0.0, 0.0
    return float(exc), float(inc)


class PetpoojaPayloadBuilder:
    """
    Builds the Petpooja JSON orderinfo payload from an Order and its catalog.

    Fixes applied:
    1. Timestamp alignment: preorder_date/time matches created_on for immediate orders.
    2. Per-unit pricing: final_price is per unit, not total quantity.
    3. Per-unit taxes: item_tax amounts are per unit, not total quantity.
    4. Tax aggregation: Global Tax.details contains total amounts across all items.
    5. Variation support: variation_name and variation_id are filled from the selected variation.
       The variation price is used instead of the base item price (base is "0" for variation items).
    6. Addon support: AddonItem.details is built from the customer's addon selections,
       resolved against the catalog addongroups index.
    """

    def __init__(
        self,
        order: Order,
        catalog: Dict,
        *,
        menu_sharing_code: str,
        callback_url: str,
        res_name: str,
    ):
        self.order = order
        self.catalog = catalog
        self._menu_sharing_code = menu_sharing_code
        self._callback_url = callback_url
        self._res_name = res_name
        # Build a flat index: addonitemid → addon item dict, for fast lookup during order build.
        # This avoids nested loops for every order item.
        self._addon_item_index: Dict[str, Dict] = {
            item["addonitemid"]: item
            for ag in catalog.get("addongroups", [])
            for item in ag.get("addongroupitems", [])
        }

    def build(self) -> Dict[str, Any]:
        catalog_items = self.catalog.get("items", [])
        tax_index = {t["taxTypeId"]: t for t in self.catalog.get("taxTypes", [])}

        order_items, tax_aggregation = self._build_order_items(catalog_items, tax_index)
        final_global_taxes = self._format_global_taxes(tax_aggregation)

        tw_exc, tw_inc = _order_takeaway_exc_inc(self.order)
        packing_tax = money(tw_inc - tw_exc) if tw_inc > 0 and tw_exc >= 0 else 0.0
        item_tax_sum = sum(float(t["tax"]) for t in final_global_taxes)
        tax_total_all = money(item_tax_sum + packing_tax)

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
                            "res_name": self._res_name,
                            "address": "Restaurant Address",  # TODO: Use actual restaurant address
                            "contact_information": "9999999999",  # TODO: Use actual contact number
                            "restID": self._menu_sharing_code,
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

                            # Packing / takeaway charges (same bucket as Petpooja packing)
                            "packing_charges": str(money(tw_exc)) if tw_exc > 0 else "0",
                            "pc_tax_amount": str(packing_tax) if packing_tax > 0 else "0",
                            "pc_tax_percentage": "5" if tw_exc > 0 else "0",
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
                            "tax_total": str(tax_total_all),
                            "discount_type": "F",
                            "total": str(self.order.total_amount_include_tax),

                            # Additional fields
                            "description": "",
                            "enable_delivery": 0,
                            "min_prep_time": 20,
                            "callback_url": self._callback_url,
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

    def _resolve_variation(self, src_item: dict, variation_id: Optional[str]) -> Optional[dict]:
        """
        Look up the customer's selected variation from the catalog item's variation list.

        variation_id is the 'id' field (the unique row ID), NOT 'variationid'.
        Returns the variation dict if found, else None.
        """
        if not variation_id:
            return None
        for var in src_item.get("variation", []):
            if str(var.get("id")) == str(variation_id):
                return var
        return None

    def _build_addon_details(self, addon_items: List[Dict]) -> List[Dict]:
        """
        Resolve the customer's addon selections against the catalog index.

        Each entry in addon_items: { addon_item_id: str, quantity: int }
        Returns a list of PetPooja AddonItem detail dicts.
        """
        details = []
        for spec in (addon_items or []):
            addon_item_id = str(spec.get("addon_item_id", ""))
            addon_info = self._addon_item_index.get(addon_item_id)
            if not addon_info:
                # The addon item no longer exists in the catalog (was deactivated);
                # skip silently so the order still goes through.
                continue
            details.append({
                "id": addon_info["addonitemid"],
                "name": addon_info["addonitem_name"],
                "price": str(addon_info.get("addonitem_price", "0")),
                "quantity": str(spec.get("quantity", 1)),
            })
        return details

    def _build_order_items(self, catalog_items: list, tax_index: dict) -> tuple[list, dict]:
        """
        Builds the list of Petpooja order items and accumulates global tax totals.

        For each order item:
        - `price` is precisely the unit price of the base item or variation.
        - `final_price` is precisely `price - (item_discount / quantity)`.
        - Taxes are calculated per unit and included in global aggregation.
        - Addons are resolved and listed.

        Returns (order_items, tax_aggregation).
        """
        order_items = []
        tax_aggregation: Dict[str, Any] = {}

        for item_spec in self.order.item_specs_for_payload():
            # 1. Base Item Resolution
            src_item = find_item(catalog_items, item_spec.get("sku_code"))
            if not src_item:
                raise ValueError(f"SKU {item_spec.get('sku_code')} not found in catalog")

            quantity = item_spec["quantity"]

            # 2. Extract Variation details if the order has one
            variation_id = item_spec.get("variation_id")
            selected_variation = self._resolve_variation(src_item, variation_id)
            if selected_variation:
                variation_name = selected_variation.get("name", "")
                variation_id_out = str(selected_variation.get("id", ""))
            else:
                variation_name = ""
                variation_id_out = ""

            # 3. Old Calculation Method!
            # build_sale_item returns total amounts for the entire quantity of this sku.
            # We override the price with the actual catalog price (either variation or base)
            pricing_item = dict(src_item)
            if selected_variation:
                pricing_item["price"] = float(selected_variation.get("price", 0))

            line, _tax_inc, _tax_exc = build_sale_item(pricing_item, quantity, tax_index)

            # Revert to old pricing strategy!
            # Petpooja expects per-unit pricing, not totals BEFORE discount
            unit_price = float(pricing_item.get("price", 0))
            item_discount_per_unit = 0.0  # TODO: Implement discounts if needed
            unit_final_price = unit_price - item_discount_per_unit

            # Revert to old per-unit tax amounts calculation
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

                # Accumulate total tax amounts for global Tax section
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

            # FIX #6: Build addon details from customer selections
            addon_items_spec = item_spec.get("addon_items", [])
            addon_details = self._build_addon_details(addon_items_spec)

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
                "variation_name": variation_name,
                "variation_id": variation_id_out,
                "AddonItem": {"details": addon_details},
            })

        return order_items, tax_aggregation

    def _format_global_taxes(self, tax_aggregation: dict) -> list:
        """Formats accumulated tax totals into Petpooja's global Tax.details format."""
        result = []
        for tax_data in tax_aggregation.values():
            tax_data["tax"] = money(tax_data["tax"])
            result.append(tax_data)
        return result
