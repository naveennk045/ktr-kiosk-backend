# Dashboard API Documentation

This document references the APIs used by the Admin Dashboard.

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
  "cashRupees": 7500.00,
  "manualRupees": 0.00
}
```

`upiRupees` maps from stored payment method `QR` (UPI QR). `manualRupees` is the `MANUAL` payment method if used.

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

### Get EDC Configurations
**Endpoint**: `GET /admin/edc-config`
**Purpose**: Fetches the list of configured EDC terminals and their mappings to stores and merchant IDs.

**Response**:
```json
[
  {
    "id": 1,
    "merchant_id": "M001",
    "store_id": "STORE-001",
    "terminal_id": "T001",
    "mid_on_device": "12345",
    "tid_on_device": "67890"
  },
  {
    "id": 2,
    "merchant_id": "M001",
    "store_id": "STORE-002",
    "terminal_id": "T002",
    "mid_on_device": null,
    "tid_on_device": null
  }
]
```
