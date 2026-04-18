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
**Header**: `X-Store-Id` (numeric id or `store_code`)

**Purpose**: Pine Labs–related setup for the current store: shared API credentials flag plus per-device **`kiosk_terminals`** (PineLabs Client ID, PineLabs Store ID, labels).

**Response** (shape; see OpenAPI `/docs` for exact model):

```json
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
```

The legacy **`GET /admin/edc-config`** route has been replaced by this endpoint.
