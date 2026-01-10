# Dashboard API Documentation

This document references the APIs used by the Admin Dashboard.

## 1. Analytics (KPI Header)

### Get Analytics Summary
**Endpoint**: `GET /analytics/summary`
**Purpose**: Fetches top-level metrics for the dashboard header.

**Response**:
```json
{
  "totalRevenue": 42500.00,
  "totalOrders": 120,
  "pendingPayments": 3,
  "syncFailures": 5
}
```

---

## 2. Order Management

### Master Order Grid
**Endpoint**: `GET /orders`
**Purpose**: Fetches a paginated list of orders with sorting and filtering options.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 0 | Page number (0-indexed) |
| `size` | int | 20 | Items per page |
| `sortBy` | str | `created_at` | Field to sort by (`created_at`, `total_amount`) |
| `sortDir` | str | `desc` | Sort direction (`asc`, `desc`) |
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
