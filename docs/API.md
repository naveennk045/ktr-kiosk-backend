# KTR Kiosk Server — HTTP API

FastAPI service (default port **8080** via Uvicorn). Interactive schemas: **`GET /docs`** (Swagger UI) and **`GET /redoc`** (ReDoc).

## Conventions

| Topic | Detail |
|--------|--------|
| **Content-Type** | JSON unless noted (`application/json`). |
| **CORS** | `allow_origins=["*"]` (adjust for production if needed). |
| **Request tracing** | All HTTP responses include `X-Request-Id`. Send your own `X-Request-Id` header to correlate frontend actions with backend logs. |
| **Store scoping** | Most kiosk and dashboard routes require header **`X-Store-Id`**. Exception: **`GET /admin/kiosk-config`** returns **all** active stores (no header). Value is either the numeric **`stores.id`** or case-insensitive **`store_code`**. Missing header where required → **400**; unknown/inactive store → **404**. |
| **Payment routes** | **`X-Store-Id` is not used.** Store is taken from the **order** row (`orders.store_id`) created at order time. |
| **Petpooja menu webhook** | No `X-Store-Id`; the store is resolved from **`petpooja_restaurant_id`** in the payload vs `store_petpooja_credentials`. |

**Kitchen & token displays:** see **`docs/KDS-TMS-client-guide.md`** for running the stack, `/kds` and `/tms` APIs, WebSocket/SSE, Redis events, and frontend checklists.

---

## Root

| Method | Path | Headers | Description |
|--------|------|---------|-------------|
| `GET` | `/` | — | Health-style welcome message. |

---

## Catalog (`/catalog`)

Requires **`X-Store-Id`**. Uses Redis + DB menu + Petpooja (via `CatalogService`).

| Method | Path | Query / body | Description |
|--------|------|----------------|-------------|
| `GET` | `/catalog/` | `channel` (required) | Returns processed catalog JSON for the channel (cache → DB menu → live API fallback). |
| `DELETE` | `/catalog/cache` | `channel` (required) | Deletes Redis key `petpooja_catalog_data_{store_id}_{channel}`. |
| `GET` | `/catalog/cache-stats` | — | Lists cached channel suffixes for this store. |

---

## Orders — create (`POST /orders/`)

Requires **`X-Store-Id`**.

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/orders/` | [`OrderCreateRequest`](#ordercreaterequest) | Creates order, tax/KOT logic via `OrderService`. |

**Responses:** **`200`** with [`OrderCreateResponse`](#ordercreateresponse); **`400`** validation; **`500`** generic failure.

### `OrderCreateRequest`

| Field | Type | Notes |
|-------|------|--------|
| `channel` | string | e.g. kiosk channel name. |
| `order_type` | `DINEIN` \| `TAKEAWAY` | Enum. |
| `items` | array | Each item: `item_skuid` (SKU), `quantity`, optional `variation_id`, optional `addon_items` (`addon_item_id`, `quantity`). |
| `total_amount_include_tax` | number | |
| `total_amount_exclude_tax` | number | |
| `takeaway_charges_without_tax` | number | Default `0`; for `TAKEAWAY`, server may recalculate. |
| `takeaway_charges_with_tax` | number | Default `0`. |

### `OrderCreateResponse`

JSON uses serialization aliases for amounts:

```json
{
  "order_id": "KTR-BFA7DE6482",
  "total_amount_include_tax": 420.0,
  "total_amount_exclude_tax": 400.0,
  "kot_code": "KTR-23",
  "order_type": "DINEIN",
  "takeaway_charges_without_tax": 0.0,
  "takeaway_charges_with_tax": 0.0
}
```

| Field | Description |
|-------|-------------|
| `order_id` | Business order id (e.g. `KTR-…`). |
| `kot_code` | Generated KOT label. |
| `order_type` | `DINEIN` or `TAKEAWAY`. |
| Takeaway charge fields | Mirrors request/recalculation. |

---

## Orders — dashboard reads (`GET /orders/…`)

Requires **`X-Store-Id`**. Same path prefix as create; method distinguishes **GET** (list/detail) vs **POST** (create).

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| `GET` | `/orders/` | `page`, `size`, `sortBy`, `sortDir`, `period`, `status`, `search` | Paginated grid; `period`: `today`, `yesterday`, `last_week`, `all_time` (IST). |
| `GET` | `/orders/{order_id}` | — | Full order detail for dashboard. |

Response models: `OrderGridResponse`, `OrderDetailResponse` (see `/docs`).

---

## Analytics (`/analytics`)

Requires **`X-Store-Id`**. All endpoints count **COMPLETED** orders only in **Asia/Kolkata (IST)** windows.

### Summary KPIs

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| `GET` | `/analytics/summary` | `period` (default `all_time`) | Revenue, order counts, payment mix for completed orders. |

### Item-wise Analytics

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| `GET` | `/analytics/items/top` | `period` (default `today`), `limit` 1–100 (default `10`) | **Top N items** ranked by total quantity sold. |
| `GET` | `/analytics/items/daily` | `period` (default `today`), `sku` (optional) | **Per-day item counts** — how many of each item ordered each day (IST date). Optionally filter to a single SKU for trend view. |
| `GET` | `/analytics/items/summary` | `period` (default `today`) | **Full item-wise summary**: all items with qty, revenue, order count, avg qty/order. |

#### `period` values (all endpoints)

| Value | Window (IST) |
|-------|-------------|
| `today` | From 00:00 IST today through now |
| `yesterday` | Full previous IST calendar day |
| `last_week` | From 00:00 IST seven days ago through now |
| `all_time` | No date filter |

#### Response — `GET /analytics/items/top`

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
    }
  ]
}
```

#### Response — `GET /analytics/items/daily?period=last_week`

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
    }
  ]
}
```

Pass `?sku=10550601` to drill into a single item's daily trend.

#### Response — `GET /analytics/items/summary`

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
    }
  ]
}
```

---

## Payments (`/payments`)

**No `X-Store-Id` header.** Resolve store from the existing **`order_id`**.

### Dynamic QR (PhonePe)

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/payments/qr/init` | `order_id`, `amount_paise`, `terminal_id` (optional) | Initiates UPI QR; returns `qr_string`, `expires_at`. |
| `GET` | `/payments/qr/status/{order_id}` | — | Poll payment / KDS-related fields. |

### EDC (Pine Labs)

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/payments/edc/init` | `order_id`, `amount_paise`, `terminal_id` (**required**) | Push amount to Pine Labs terminal (kiosk `terminal_id` = PineLabs Client ID). |
| `GET` | `/payments/edc/status/{order_id}` | — | Poll card payment status; includes provider raw payload. |

Response `provider` message is driven by Pine Labs (`EDCInitiateResponse` uses provider label **Pine Labs EDC** in code).

### Cash

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/payments/cash/init` | `order_id`, `amount_paise`, `terminal_id` (optional), `pin` (staff PIN) | Validates PIN against `cash_pin` for the order’s store; completes cash flow. |

### PhonePe webhook

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/payments/webhook/phonepe` | Server-to-server callback: JSON with base64 `response`, header **`X-VERIFY`**. Signature verified using `StorePhonePeCredentials` for the order’s store. Returns `{"status":"ok"}` on acceptance. |

---

## Admin (`/admin`)

| Method | Path | Store selection | Description |
|--------|------|-----------------|-------------|
| `GET` | `/admin/stores` | **None** | Returns stores with terminal list + `petpooja_configured`/`phonepe_configured`/`pinelabs_configured`. Query: `active_only=true|false` (default `true`). |
| `GET` | `/admin/stores/{store_ref}` | **None** | Returns one store detail by numeric `id` or `store_code` (case-insensitive). |
| `GET` | `/admin/analytics/summary` | **None** | Owner analytics across all stores (combined totals + per-store breakdown). Query: `period=today|yesterday|last_week|all_time` (default `today`), `active_only=true|false` (default `true`). Completed orders only. |
| `GET` | `/admin/analytics/store-insights` | **None** | Owner decision insights per store: top ordered items, AOV, payment split, top channel. Query: `period`, `active_only`, optional `store_ids`, `store_codes`, `top_n` (default `5`). |
| `GET` | `/admin/accounting/settlement` | **None** | Detailed financial breakdown by store for reconciliation. Gross vs Net, Total Tax, Gateway (PineLabs) breakdown by Terminal ID, Cash breakdown by Staff. Query: `period=today|yesterday|last_week|all_time`, `active_only=true|false`, optional `store_ids`, `store_codes`. Completed orders only. |
| `GET` | `/admin/transactions` | **None** | Owner transaction grid across stores with filters and pagination. |
| `GET` | `/admin/kiosk-config` | **None** | JSON **array** of all **active** stores; each element has **`store_id`**, **`store_code`**, **`store_name`**, **`pinelabs_configured`**, and **`terminals`** (PineLabs `terminal_id`, `pinelabs_store_id`, labels). Use this to configure any outlet; then use **`X-Store-Id`** on other routes. |
| `GET` | `/admin/cash-pins` | **`X-Store-Id`** required | Staff **`id`** + **`staff_name`** only (no PIN values). |
| `POST` | `/admin/cache/invalidate` | **`X-Store-Id`** required | Clears Redis cache for that store’s credentials/meta. |
| `GET` | `/admin/logs` | **None** | Returns latest parsed `app.log` entries for frontend log table. Query: `lines` (default `200`, max `2000`), `contains` (optional case-insensitive filter). |
| `GET` | `/admin/logs/stream` | **None** | SSE stream for live logs from `app.log`. Query: `initial_lines` (default `50`), `contains` (optional filter). Emits `entry` objects suitable for table append. |

### Admin logs API examples

#### `GET /admin/logs?lines=300&contains=Access`

```json
{
  "path": "/root/ktr-kiosk-backend/app.log",
  "count": 2,
  "entries": [
    {
      "timestamp": "2026-05-02 12:24:46,759",
      "level": "INFO",
      "logger": "app.main",
      "message": "[Access][a0d2...] request_started method=POST path=/payments/qr/init query=- client_ip=10.0.0.3 ua=Mozilla/5.0",
      "raw": "2026-05-02 12:24:46,759 - [INFO] - app.main - [Access][a0d2...] request_started method=POST path=/payments/qr/init query=- client_ip=10.0.0.3 ua=Mozilla/5.0"
    }
  ]
}
```

#### `GET /admin/logs/stream?contains=payment&initial_lines=100`

SSE `message` event payload:

```json
{
  "type": "log",
  "entry": {
    "timestamp": "2026-05-02 12:24:47,040",
    "level": "INFO",
    "logger": "app.services.order_service",
    "message": "KDS sync success | order_id=KTR-1FADC67110 | petpooja_order_id=KTR-1FADC67110",
    "raw": "2026-05-02 12:24:47,040 - [INFO] - app.services.order_service - KDS sync success | order_id=KTR-1FADC67110 | petpooja_order_id=KTR-1FADC67110"
  }
}
```

Frontend table suggestion (columns): `timestamp`, `level`, `logger`, `message`.

### Store discovery examples

#### `GET /admin/stores?active_only=true`

```json
[
  {
    "store_id": 1,
    "store_code": "KTRBANDRA",
    "store_name": "KTR Bandra",
    "is_active": true,
    "petpooja_configured": true,
    "phonepe_configured": true,
    "pinelabs_configured": true,
    "terminals": [
      {
        "id": 1,
        "terminal_id": "MST2512191529159615649890",
        "pinelabs_store_id": "KTRVERSOVA",
        "mid_on_device": null,
        "label": "Main kiosk",
        "is_active": true
      }
    ]
  }
]
```

#### `GET /admin/stores/KTRBANDRA`

Returns one object in the same schema as above.

### Multi-store analytics example

#### `GET /admin/analytics/summary?period=today&active_only=true`

```json
{
  "period": "today",
  "totalRevenue": 12540.0,
  "totalOrders": 142,
  "dineInOrders": 48,
  "takeAwayOrders": 94,
  "upiRupees": 8240.0,
  "cardRupees": 3110.0,
  "cashRupees": 1190.0,
  "stores": [
    {
      "store_id": 1,
      "store_code": "KTRBANDRA",
      "store_name": "KTR Bandra",
      "totalRevenue": 7420.0,
      "totalOrders": 83,
      "dineInOrders": 21,
      "takeAwayOrders": 62,
      "upiRupees": 5010.0,
      "cardRupees": 1700.0,
      "cashRupees": 710.0
    },
    {
      "store_id": 2,
      "store_code": "KTRVERSOVA",
      "store_name": "KTR Versova",
      "totalRevenue": 5120.0,
      "totalOrders": 59,
      "dineInOrders": 27,
      "takeAwayOrders": 32,
      "upiRupees": 3230.0,
      "cardRupees": 1410.0,
      "cashRupees": 480.0
    }
  ]
}
```

### Owner Accounting & Settlement example

#### `GET /admin/accounting/settlement?period=today`

```json
{
  "period": "today",
  "stores": [
    {
      "store_id": 1,
      "store_code": "KTRBANDRA",
      "grossSales": 7420.0,
      "netSales": 7066.67,
      "totalTax": 353.33,
      "takeawayChargesCollected": 150.0,
      "totalUpi": 5010.0,
      "totalCard": 1700.0,
      "totalCash": 710.0,
      "pineLabsSettlement": [
        {
          "terminalId": "MST2512191529159615649890",
          "cardAmount": 1700.0,
          "cardTxnCount": 5
        }
      ],
      "cashSettlement": [
        {
          "staffName": "Rahul",
          "cashAmount": 710.0,
          "cashTxnCount": 3
        }
      ]
    }
  ]
}
```

### Owner transactions filters

#### `GET /admin/transactions`

Supported query params:

- `page`, `size`
- `sortBy=created_at|amount|order_id`, `sortDir=asc|desc`
- `period=today|yesterday|last_week|all_time`
- `start_at`, `end_at` (ISO datetime; optional fine-grained range)
- `active_only=true|false`
- `store_ids` (CSV, e.g. `1,2`)
- `store_codes` (CSV, e.g. `KTRBANDRA,KTRVERSOVA`)
- `order_type=DINEIN|TAKEAWAY`
- `payment_status=PENDING|COMPLETED|FAILED`
- `payment_method=QR|CARD|CASH|MANUAL`
- `kds_status=NOT_POSTED|PENDING|POSTED|FAILED`
- `channel`
- `terminal_id`
- `search` (matches `order_id` and `kot_code`)
- `min_amount`, `max_amount`

Example:

`/admin/transactions?period=today&store_codes=KTRBANDRA,KTRVERSOVA&order_type=TAKEAWAY&payment_status=COMPLETED&payment_method=QR&search=KTR-&sortBy=amount&sortDir=desc&page=0&size=20`

### Store insights example

#### `GET /admin/analytics/store-insights?period=today&top_n=5`

```json
{
  "period": "today",
  "totalRevenue": 12540.0,
  "totalOrders": 142,
  "averageOrderValue": 88.31,
  "stores": [
    {
      "store_id": 1,
      "store_code": "KTRBANDRA",
      "store_name": "KTR Bandra",
      "totalRevenue": 7420.0,
      "totalOrders": 83,
      "averageOrderValue": 89.4,
      "dineInOrders": 21,
      "takeAwayOrders": 62,
      "upiRupees": 5010.0,
      "cardRupees": 1700.0,
      "cashRupees": 710.0,
      "topChannel": "Palas Kiosk",
      "topItems": [
        { "itemName": "Hot Filter Coffee", "quantity": 45, "revenue": 4050.0 },
        { "itemName": "Cold Filter Coffee", "quantity": 28, "revenue": 3360.0 }
      ]
    }
  ]
}
```

---

## Petpooja (`/petpooja`)

Inbound integrations (typically configured in Petpooja dashboard).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/petpooja/webhook/menu` | — | Menu push: `application/x-www-form-urlencoded` with `restdata` **or** raw JSON. Resolves store by restaurant id in payload vs `store_petpooja_credentials`; persists `menus` row and refreshes catalog cache when Redis is up. |
| `POST` | `/petpooja/callback` | — | Order status callback (logged; returns generic success). |

---

## Error handling (typical)

| Code | When |
|------|------|
| **400** | Missing `X-Store-Id` where required; bad request body. |
| **401** | PhonePe webhook signature mismatch. |
| **404** | Store not found; order not found (dashboard detail). |
| **503** | Redis unavailable where required; Petpooja not configured for store. |

---

## Related docs

- Dashboard UI integration: [`frontend_dashboard_guide.md`](./frontend_dashboard_guide.md)
- Older endpoint notes (partially superseded): [`api_endpoints.md`](./api_endpoints.md), [`dashboard_api.md`](./dashboard_api.md)

For request/response field-level detail, prefer **`/docs`** generated from Pydantic models.
