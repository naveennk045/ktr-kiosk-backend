# Dashboard API Documentation

**Full HTTP reference (all services):** [`API.md`](./API.md).

This document focuses on the **Admin Dashboard** APIs.

**Frontend implementation guide** (requests, responses, UX, copy-paste build prompt): see [`frontend_dashboard_guide.md`](./frontend_dashboard_guide.md).

## 1. Analytics (KPI Header)

### Get Analytics Summary
**Endpoint**: `GET /analytics/summary`
**Purpose**: Business KPIs for **completed orders only**, in **Asia/Kolkata (IST)**. KDS / pending counts are not included.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | str | `all_time` | `today` — from today 00:00 IST through now; `yesterday` — full previous IST calendar day; `last_week` — from 00:00 seven days ago through now; `all_time` — no date filter |

**Response**:
```json
{
  "period": "today",
  "totalRevenue": 42500.00,
  "totalOrders": 120,
  "dineInOrders": 70,
  "takeAwayOrders": 50,
  "upiRupees": 20000.00,
  "cardRupees": 15000.00,
  "cashRupees": 7500.00
}
```

`upiRupees` maps from stored payment method `QR` (UPI QR). `cashRupees` includes **`CASH` and `MANUAL`** payment amounts so KPIs stay in three buckets without a separate manual field.

---

## 2. Item-wise Analytics

All three endpoints below:
- Require **`X-Store-Id`** header
- Count only **COMPLETED** orders
- Use **Asia/Kolkata (IST)** for date boundaries

### 2.1 Top Items

**Endpoint**: `GET /analytics/items/top`  
**Purpose**: Rank items by total quantity sold — useful for the "bestsellers" widget.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | str | `today` | `today`, `yesterday`, `last_week`, `all_time` |
| `limit` | int | `10` | Number of top items (1–100) |

**Response**:
```json
{
  "period": "today",
  "limit": 10,
  "items": [
    {
      "sku": "10550601",
      "item_name": "Hot Filter Coffee",
      "total_quantity": 45,
      "total_revenue": 4050.0,
      "order_count": 38
    },
    {
      "sku": "10550471",
      "item_name": "Paneer Mexican Sizzler",
      "total_quantity": 28,
      "total_revenue": 11172.0,
      "order_count": 21
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `sku` | `item_skuid` from `order_items` |
| `item_name` | Display name from the order line |
| `total_quantity` | Sum of units sold across all orders in the period |
| `total_revenue` | Sum of `price × quantity` for this item |
| `order_count` | Number of distinct orders that contained this item |

---

### 2.2 Daily Item Counts

**Endpoint**: `GET /analytics/items/daily`  
**Purpose**: How many of each item was ordered **per day** — the core "daily item analytics" view.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | str | `today` | `today`, `yesterday`, `last_week`, `all_time` |
| `sku` | str | *(omit)* | If provided, returns only rows for that one item SKU (drill-down / trend chart) |

**Response**:
```json
{
  "period": "last_week",
  "sku_filter": null,
  "rows": [
    {
      "date": "2026-04-26",
      "sku": "10550601",
      "item_name": "Hot Filter Coffee",
      "total_quantity": 18,
      "order_count": 15
    },
    {
      "date": "2026-04-26",
      "sku": "10550471",
      "item_name": "Paneer Mexican Sizzler",
      "total_quantity": 12,
      "order_count": 10
    },
    {
      "date": "2026-04-27",
      "sku": "10550601",
      "item_name": "Hot Filter Coffee",
      "total_quantity": 22,
      "order_count": 19
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `date` | IST calendar date (`YYYY-MM-DD`) |
| `sku` | Item SKU |
| `item_name` | Display name |
| `total_quantity` | Units sold that day |
| `order_count` | Distinct orders that day containing this item |
| `sku_filter` | Echo of the `?sku=` param (or `null`) |

**Tip**: Pass `?sku=10550601&period=last_week` to power a single-item line/bar chart.

---

### 2.3 Item Summary

**Endpoint**: `GET /analytics/items/summary`  
**Purpose**: Full per-item breakdown for a period — all items with quantity, revenue, order count, and average.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | str | `today` | `today`, `yesterday`, `last_week`, `all_time` |

**Response**:
```json
{
  "period": "today",
  "total_items_sold": 312,
  "unique_items": 24,
  "items": [
    {
      "sku": "10550601",
      "item_name": "Hot Filter Coffee",
      "total_quantity": 45,
      "total_revenue": 4050.0,
      "order_count": 38,
      "avg_quantity_per_order": 1.18
    },
    {
      "sku": "10550471",
      "item_name": "Paneer Mexican Sizzler",
      "total_quantity": 28,
      "total_revenue": 11172.0,
      "order_count": 21,
      "avg_quantity_per_order": 1.33
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `total_items_sold` | Grand total of all units sold (sum of all `total_quantity`) |
| `unique_items` | Number of distinct SKUs |
| `avg_quantity_per_order` | `total_quantity ÷ order_count` for that item |

---

## 2. Order Management

### Master Order Grid
**Endpoint**: `GET /orders`
**Purpose**: Paginated list of orders with the **same `period` windows** as `/analytics/summary` (filters by `created_at` in IST).

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 0 | Page number (0-indexed) |
| `size` | int | 20 | Items per page |
| `sortBy` | str | `created_at` | Field to sort by (`created_at`, `total_amount`) |
| `sortDir` | str | `desc` | Sort direction (`asc`, `desc`) |
| `period` | str | `all_time` | Same as analytics: `today`, `yesterday`, `last_week`, `all_time` |
| `status` | str | null | Filter by payment status (e.g., `PENDING`, `COMPLETED`) |
| `search` | str | null | Search by Order ID (e.g., `KTR-80...`) |

**Response**:
```json
{
  "content": [
    {
      "orderRefId": "KTR-80F0A9B176",
      "orderId": "KTR-80F0A9B176",
      "kotCode": "KTR-42",
      "orderType": "DINEIN",
      "paymentType": "QR",
      "location": "Palas Kiosk",
      "amount": 420.00,
      "paymentStatus": "PENDING",
      "erpStatus": "NOT_POSTED",
      "itemsSummary": "Bangaluru Benne... (+1 more)",
      "createdAt": "2026-01-08T04:12:39Z"
    }
  ],
  "totalPages": 15,
  "totalElements": 300
}
```

`orderId` matches `orderRefId` (business order id). `orderType` is `DINEIN` or `TAKEAWAY`. `paymentType` is `QR`, `CARD`, `CASH`, or `MANUAL` when set, or `null` if payment is not chosen yet.

### Order Detail View
**Endpoint**: `GET /orders/{order_id}`
**Purpose**: Fetches full details for a specific order, including raw payment metadata.

**Response**:
```json
{
  "orderRefId": "KTR-80F0A9B176",
  "location": "Palas Kiosk",
  "amount": 420.00,
  "paymentStatus": "PENDING",
  "erpStatus": "FAILED",
  "items": [
      { "name": "Bangaluru Benne", "qty": 2, "price": 100 }
  ],
  "paymentMeta": {
      "provider": "PhonePe",
      "transactionId": "...",
      "raw_response": { ... }
  },
  "createdAt": "2026-01-08T04:12:39Z"
}
```

---

## 3. Configuration

### Kiosk / terminal config (Pine Labs)

**Endpoint**: `GET /admin/kiosk-config`  
**Headers**: none — returns **every** active store so the client can pick an outlet and read `store_id` / terminals.

**Purpose**: Pine Labs–related setup **per store**: shared API credentials flag plus per-device **`kiosk_terminals`** (PineLabs Client ID, PineLabs Store ID, labels).

**Response**: JSON **array** (one object per active store); see OpenAPI `/docs` for the exact model.

```json
[
  {
    "store_id": 1,
    "store_code": "KTR-BANDRA",
    "store_name": "KTR Bandra",
    "pinelabs_configured": true,
    "terminals": [
      {
        "id": 1,
        "terminal_id": "4724310",
        "pinelabs_store_id": "1570451",
        "mid_on_device": "741921",
        "label": "KTR Bandra — terminal 1",
        "is_active": true
      }
    ]
  }
]
```

The legacy **`GET /admin/edc-config`** route has been replaced by this endpoint.
