# Petpooja Pricing Logic & Math Rules
**Last Updated:** March 2026

This document outlines the exact flow of how item calculations (specifically regarding Add-ons and Variations) are processed from the moment the KTR backend receives an order, through internal database storage, and finally mapping to the external Petpooja Sync API payload.

---

## 1. Internal Database Pricing (`order_service.py`)

When the KTR frontend submits an order to the backend API (`/api/orders`), the backend must calculate the true cost of the items to save an accurate POS receipt in the local database.

The `unit_price` for each line item is resolved dynamically:

*   **Base Items:** If it's a standard item (e.g., standard Coke), the system uses the base catalog `price`.
*   **Variations:** If the customer orders a "Pizza - Medium", the base Pizza catalog price might be `$0.00` because you must choose a size. The backend detects the `variation_id`, searches the catalog's variation array, and replaces the base price with the true selected Variation Price to prevent recording a $0.00 order.
*   **Add-ons:** If the customer includes add-ons (e.g., "Extra Cheese ($10)"), the backend iterates through the selected `addon_items`, finds their prices in the catalog's `addongroups` index, and adds their costs to the `unit_price`.

**Result:** The local order model strictly calculates `total_amount_include_tax` iteratively across all items.

---

## 2. Petpooja Line Item Pricing (`petpooja_payload_builder.py`)

When the backend synchronizes the order object to Petpooja (`POST /api/orders`), Petpooja requires a highly specific JSON schema. They expect line items to be logically separated from global totals.

Here is how the KTR system maps the line items into the `OrderItem.details` array:

*   **`price`**: Sent strictly as the **Single Unit Price** of the base item or variation, entirely ignoring add-on costs.
*   **`final_price`**: Computed as the `price` subtracting any per-unit item discounts.
*   **`item_tax`**: Petpooja strictly expects taxes to be calculated for a **single unit**, not for the whole quantity chunk. The KTR backend runs `build_sale_item()`, calculates the total block tax, and then divides it by the `quantity` ordered to supply Petpooja the per-unit float.
*   **`AddonItem.details[].price`**: Add-on prices are NOT summed into the primary item `price`. They are nested into this subset array with their explicit original cost. Petpooja's external POS engines will sum these back up upon receipt.

---

## 3. Petpooja Global Totals (`petpooja_payload_builder.py`)

At the bottom of the Petpooja payload sits the `Order.details` dictionary indicating the entire receipt's global totals. 

To maintain parity with legacy internal POS logic, KTR maps these precisely:

*   **`tax_total`**: The mathematical sum of all accumulated unit taxes across the entire order.
*   **`total`**: Mapped verbatim straight to the KTR database's `order.total_amount_include_tax`. This enforces that Petpooja receives the exact grand total that the local KTR backend expects to process (inclusive of variations, add-ons, and local taxes).
*   **`collect_cash`**: Mapped verbatim to `order.total_amount_include_tax` (strictly if the customer's payment method was cash), signaling the local till to expect that exact amount.

### Summary

Historically, `order_service.py` was unable to resolve prices from variations or add-ons deep inside the nested catalog JSON. By pulling the data from `variation_id` and indexing the `addongroups`, the local subsystem correctly generates receipts matching what Petpooja mathematically derives on their own end.
