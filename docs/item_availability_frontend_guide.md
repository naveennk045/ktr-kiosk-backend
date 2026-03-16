# Frontend Guide: Item Availability (ON/OFF)

This document explains how to integrate the new Item Availability (Stock Management) feature into the Admin Dashboard and how it affects the Kiosk Catalog.

---

## 1. Admin Dashboard Integration

The Admin Dashboard should use these endpoints to manage whether an item is available for sale.

### Update Item Availability
**Endpoint**: `POST /admin/catalog/availability`  
**Purpose**: Turn an item ON or OFF.

**Request Body**:
```json
{
  "sku_code": "10550557",
  "is_available": false
}
```
*   `sku_code`: The unique `itemId` of the product.
*   `is_available`: Set to `false` to mark the item as "Sold Out/Inactive". Set to `true` to bring it back.

---

### List All Overrides
**Endpoint**: `GET /admin/catalog/availability`  
**Purpose**: Fetches a list of all items that have been manually overridden. Use this to show which items are currently "OFF" in your admin list.

**Response**:
```json
[
  {
    "sku_code": "10550557",
    "is_available": false,
    "updated_at": "2026-03-16T20:25:00Z"
  }
]
```

---

## 2. Kiosk Catalog Behavior

When an item is turned **OFF** in the Admin Dashboard, the backend automatically modifies the catalog response served to the kiosk.

### Catalog Response Change
**Endpoint**: `GET /catalog?channel=KIOSK`

If an item with ID `10550557` is marked as `is_available: false` in the DB:

**Before Override**:
```json
{
  "itemId": "10550557",
  "itemName": "Masala Dosa",
  "status": "Active",
  ...
}
```

**After Override (Live)**:
```json
{
  "itemId": "10550557",
  "itemName": "Masala Dosa",
  "status": "Inactive",
  ...
}
```

### Frontend Action (Kiosk)
- **Hiding Items**: The frontend should check the `status` field. If `status === "Inactive"`, the item should either be hidden from the menu or displayed with a "Sold Out" overlay.
- **Cache Invalidation**: The backend automatically clears the Redis cache when an availability is updated. The frontend just needs to re-fetch the catalog (or wait for its next periodic refresh) to see the change.

---

## 3. Implementation Notes

- **Real-time**: The backend bypasses the 24-hour cache for availability checks. Changes appear as soon as the catalog is re-requested.
- **SKU Based**: Availability is tracked by the Petpooja `itemId` (mapped to `skuCode` in our system).
