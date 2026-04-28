# KTR Kiosk Server — HTTP API

FastAPI service (default port **8080** via Uvicorn). Interactive schemas: **`GET /docs`** (Swagger UI) and **`GET /redoc`** (ReDoc).

## Conventions

| Topic | Detail |
|--------|--------|
| **Content-Type** | JSON unless noted (`application/json`). |
| **CORS** | `allow_origins=["*"]` (adjust for production if needed). |
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

Requires **`X-Store-Id`**.

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| `GET` | `/analytics/summary` | `period` (default `all_time`) | KPI summary for **completed** orders only (IST windows). |

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
| `GET` | `/admin/kiosk-config` | **None** | JSON **array** of all **active** stores; each element has **`store_id`**, **`store_code`**, **`store_name`**, **`pinelabs_configured`**, and **`terminals`** (PineLabs `terminal_id`, `pinelabs_store_id`, labels). Use this to configure any outlet; then use **`X-Store-Id`** on other routes. |
| `GET` | `/admin/cash-pins` | **`X-Store-Id`** required | Staff **`id`** + **`staff_name`** only (no PIN values). |
| `POST` | `/admin/cache/invalidate` | **`X-Store-Id`** required | Clears Redis cache for that store’s credentials/meta. |

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
