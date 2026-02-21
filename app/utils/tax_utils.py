"""
Tax calculation utilities for Petpooja KDS payload building.

These functions were extracted from CatalogService — they are pure math
helpers with no dependency on catalog fetching or caching concerns.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional


def money(x: float) -> float:
    """Round to 2 decimal places using ROUND_HALF_UP (banker-safe for INR)."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def find_item(catalog_items: list, sku: Optional[str] = None) -> Optional[Dict]:
    """Find an active item in a catalog list by SKU code."""
    for item in catalog_items:
        if item.get("status") != "Active":
            continue
        if sku is not None and str(item.get("skuCode")) == str(sku):
            return item
    return None


def calculate_tax_amounts(
    sale_amount: float, tax_percentage: float, price_includes_tax: bool
) -> tuple[float, float]:
    """
    Returns (tax_included, tax_excluded) for a given sale amount.
    - price_includes_tax=True  → extract tax from price (inclusive calc)
    - price_includes_tax=False → add tax on top of price (exclusive calc)
    """
    if price_includes_tax:
        tax_amount = (sale_amount * tax_percentage) / (100 + tax_percentage)
        return money(tax_amount), 0.0
    else:
        tax_amount = (sale_amount * tax_percentage) / 100
        return 0.0, money(tax_amount)


def build_sale_item(src_item: Dict, qty: int, tax_index: Dict) -> tuple[Dict, float, float]:
    """
    Build a full line-item dict with tax breakdown for a given qty.
    Returns (line_dict, total_tax_included, total_tax_excluded).
    """
    qty = int(qty)
    unit_price = float(src_item["price"])
    item_amount = unit_price * qty
    price_includes_tax = bool(src_item.get("isPriceIncludesTax", False))

    taxes = []
    total_tax_included = 0.0
    total_tax_excluded = 0.0

    for tax_id in src_item.get("taxTypeIds", []):
        meta = tax_index.get(tax_id)
        if not meta:
            continue

        rate = float(meta["percentage"])
        amount_included, amount_excluded = calculate_tax_amounts(item_amount, rate, price_includes_tax)

        total_tax_included += amount_included
        total_tax_excluded += amount_excluded

        taxes.append({
            "id": str(tax_id),
            "name": meta["name"],
            "percentage": rate,
            "saleAmount": money(item_amount),
            "amountIncluded": amount_included,
            "amountExcluded": amount_excluded,
            "amount": money(amount_included + amount_excluded),
        })

    item_total_amount = money(item_amount)
    line: Dict = {
        "shortName": src_item["itemName"],
        "skuCode": src_item["skuCode"],
        "quantity": qty,
        "unitPrice": money(unit_price),
        "itemAmount": item_total_amount,
        "itemNature": "Service",
        "itemTotalAmount": item_total_amount,
    }

    if taxes:
        if total_tax_included:
            line["taxAmountIncluded"] = money(total_tax_included)
        if total_tax_excluded:
            line["taxAmountExcluded"] = money(total_tax_excluded)
        line["taxes"] = taxes

    return line, total_tax_included, total_tax_excluded


def summarize_taxes(items: List[Dict]) -> List[Dict]:
    """
    Aggregate tax amounts across multiple line items into a summary list.
    Groups by (name, percentage) key.
    """
    agg: Dict[tuple, Dict] = {}
    for item in items:
        for t in item.get("taxes", []):
            key = (t["name"], t["percentage"])
            entry = agg.setdefault(key, {
                "name": t["name"],
                "percentage": t["percentage"],
                "saleAmount": 0.0,
                "itemTaxIncluded": 0.0,
                "itemTaxExcluded": 0.0,
                "chargeTaxIncluded": 0.0,
                "chargeTaxExcluded": 0.0,
                "amountIncluded": 0.0,
                "amountExcluded": 0.0,
                "amount": 0.0,
            })
            inc = float(t.get("amountIncluded", 0.0))
            exc = float(t.get("amountExcluded", 0.0))
            entry["saleAmount"] += float(t.get("saleAmount", 0.0))
            entry["itemTaxIncluded"] += inc
            entry["itemTaxExcluded"] += exc
            entry["amountIncluded"] += inc
            entry["amountExcluded"] += exc
            entry["amount"] += float(t.get("amount", 0.0))

    # Round all float fields
    _MONEY_FIELDS = [
        "saleAmount", "itemTaxIncluded", "itemTaxExcluded",
        "chargeTaxIncluded", "chargeTaxExcluded",
        "amountIncluded", "amountExcluded", "amount",
    ]
    for v in agg.values():
        for k in _MONEY_FIELDS:
            v[k] = money(v[k])

    return list(agg.values())
