# KDS & TMS — Frontend client guide (with examples)

This document is for **frontend teams** building the **Kitchen Display System (KDS)** and **Token Management System (TMS)** against this API. It focuses on **contracts, payloads, and step-by-step examples** so you can adopt **partial quantity** flows, **`order_type`**, and live events.

For running the server, env vars, and ops, see also `docs/API.md` and project `README` if present.

---

## 1. Conventions every client must follow

### 1.1 Store header

Almost all KDS/TMS HTTP routes require:

```http
X-Store-Id: <numeric stores.id OR store store_code string>
```

Inactive or unknown stores → **404**.

### 1.2 Base paths

| App | Base path |
|-----|-----------|
| KDS | `/kds` |
| TMS | `/tms` |

### 1.3 Database migration (existing deployments)

Line items now track partial kitchen / pickup progress. On **existing** PostgreSQL databases, run **once**:

`scripts/add_order_item_quantity_tracking_columns.sql`

It adds `items_need_be_ready` and `items_need_be_collected`, backfills from `quantity` + `order_status`, and drops legacy `actual_quantity` if it exists.

---

## 2. Domain model (what each field means)

### 2.1 Order (KDS board / TMS token)

| Field | Meaning |
|-------|---------|
| `order_id` | Business id (e.g. `KTR-A1B2C3D4`) |
| `kot_code` | Customer-facing token (e.g. `KTR-7`) |
| `order_type` | **`DINEIN`** or **`TAKEAWAY`** — present on **KDS** `GET /kds/board` / WS snapshot under each order. (TMS snapshot does not include it today; derive from order if you add it server-side later.) |
| `payment_status` | Orders on KDS/TMS are only shown when **`COMPLETED`** |

### 2.2 Line (`order_items` — one row per ticket line)

| Field | Meaning |
|-------|---------|
| `id` | **`line_id`** — use this in `PATCH /kds/items/{line_id}/status` |
| `sku_code` | KDS only (TMS omits SKU) |
| `item_name` | Display name |
| **`quantity`** | **Total units ordered** on this line (never split into duplicate rows for partial ready) |
| **`items_need_be_ready`** | Units still to be marked **READY** by kitchen (starts equal to `quantity` on new orders) |
| **`items_need_be_collected`** | Units already marked ready for pickup but not yet **COLLECTED** by staff |
| **`order_status`** | Coarse enum: `NOT_ACCEPTED`, `PREPARING`, `READY`, `COLLECTED` — server **updates** this from the counters after each PATCH |

**Invariant (after server updates):** for a normal line, `items_need_be_ready + items_need_be_collected` should align with how much work is left; when both are `0`, the line is done and `order_status` becomes `COLLECTED`.

### 2.3 How `order_status` relates to counters (for UI badges)

Roughly:

- **`NOT_ACCEPTED`**: initial state after order creation (before kitchen starts).
- **`PREPARING`**: kitchen still has work, or a **mixed** state (some units waiting at counter, some still in kitchen).
- **`READY`**: all kitchen-side units for that line are done; pickup may still show `items_need_be_collected > 0`.
- **`COLLECTED`**: line fully finished.

Do not rely only on `order_status` for “how many idlis are ready”; always show **`items_need_be_ready`** / **`items_need_be_collected`** for progress bars.

---

## 3. Detailed example — 3 idlis, partial READY then COLLECTED

Assume one line:

- `line_id` = `501`
- `item_name` = `"Idli"`
- `quantity` = `3`

After payment completes, auto-transition may set kitchen to preparing; **initial snapshot** for that line typically looks like:

```json
{
  "id": 501,
  "sku_code": "IDLI-001",
  "item_name": "Idli",
  "quantity": 3,
  "items_need_be_ready": 3,
  "items_need_be_collected": 0,
  "order_status": "PREPARING"
}
```

### Step A — Kitchen accepts / keeps preparing (optional)

```http
PATCH /kds/items/501/status
Content-Type: application/json
X-Store-Id: 1

{ "status": "PREPARING" }
```

No counter change; `order_status` becomes `PREPARING` if it was not already.

### Step B — Mark **2** idlis ready (partial)

```http
PATCH /kds/items/501/status
Content-Type: application/json
X-Store-Id: 1

{ "status": "READY", "quantity": 2 }
```

**What the server does**

- Subtracts `2` from `items_need_be_ready` → `1`
- Adds `2` to `items_need_be_collected` → `2`
- Recomputes `order_status` (likely `PREPARING` because one idli is still in kitchen)

**Typical response body** (shape; numbers match your DB):

```json
{
  "store_id": 1,
  "line_id": 501,
  "order_id": "KTR-A1B2C3D4",
  "kot_code": "KTR-7",
  "item_name": "Idli",
  "quantity": 2,
  "items_need_be_ready": 1,
  "items_need_be_collected": 2,
  "order_status": "PREPARING"
}
```

**Important:** the field **`quantity` in this response is the batch size** moved by **this** PATCH (here `2`), not the line’s total ordered quantity (`3`). The line’s total is still `quantity: 3` on the next `GET /kds/board` snapshot.

**Redis:** clients also receive **`ITEM_STATUS_CHANGED`** and **`TMS_ANNOUNCE`** (with `speech` for TTS) on this PATCH when status is `READY`.

### Step C — Mark the last idli ready

```http
PATCH /kds/items/501/status
X-Store-Id: 1
Content-Type: application/json

{ "status": "READY", "quantity": 1 }
```

Now `items_need_be_ready: 0`, `items_need_be_collected: 3`, `order_status` likely **`READY`**.

### Step D — Customer collects **1** idli (partial COLLECTED)

```http
PATCH /kds/items/501/status
X-Store-Id: 1
Content-Type: application/json

{ "status": "COLLECTED", "quantity": 1 }
```

`items_need_be_collected` goes `3 → 2`. `order_status` may stay **`READY`** until all collected.

### Step E — Collect remaining **2**

```http
PATCH /kds/items/501/status
X-Store-Id: 1
Content-Type: application/json

{ "status": "COLLECTED", "quantity": 2 }
```

When both counters hit `0`, `order_status` becomes **`COLLECTED`**. The line disappears from TMS when **all** lines on that order are `COLLECTED`.

### Omitting `quantity` (full line in one tap)

If you omit `quantity`, the server uses the line’s full **`quantity`** for the cap — but **`READY`** still cannot move more than `items_need_be_ready`, and **`COLLECTED`** cannot move more than `items_need_be_collected`.

Examples:

```json
{ "status": "READY" }
```

→ moves up to **`items_need_be_ready`** units (often “all remaining in kitchen”).

```json
{ "status": "COLLECTED" }
```

→ moves up to **`items_need_be_collected`** units.

### Errors you should surface in UI

| HTTP | Typical reason |
|------|----------------|
| **400** | `quantity` > line `quantity`, or > `items_need_be_ready` / `items_need_be_collected`, or `status: "NOT_ACCEPTED"` (not allowed from KDS) |
| **404** | Wrong `line_id` or line not in this store |
| **400** | Order not paid — line not on board |

---

## 4. KDS — HTTP API

### 4.1 Endpoints

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| GET | `/kds/health` | `max_rows` optional (1–100) | Meta including `live_window_minutes` |
| GET | `/kds/board` | `max_rows` optional | Snapshot: orders + lines + `clubbed_totals` |
| PATCH | `/kds/items/{line_id}/status` | — | Update line status / partial quantities |

### 4.2 `GET /kds/board` — full example shape

```json
{
  "store_id": 1,
  "live_window_minutes": 30,
  "option": "B",
  "max_rows": 20,
  "orders": [
    {
      "id": 100,
      "store_id": 1,
      "order_id": "KTR-A1B2C3D4",
      "order_type": "TAKEAWAY",
      "kot_code": "KTR-7",
      "kot_number": 7,
      "kot_date": "2026-04-30",
      "created_at": "2026-04-30T10:00:00+00:00",
      "lines": [
        {
          "id": 501,
          "sku_code": "IDLI-001",
          "item_name": "Idli",
          "quantity": 3,
          "items_need_be_ready": 1,
          "items_need_be_collected": 2,
          "order_status": "PREPARING"
        }
      ]
    }
  ],
  "clubbed_totals": [
    { "item_name": "Idli", "quantity": 3 }
  ]
}
```

**`clubbed_totals` note:** sums **`quantity`** per `item_name` for lines where `order_status != COLLECTED`. That is **ordered volume**, not “still cooking”. For “plates still in kitchen”, use **`items_need_be_ready`** per line in UI.

### 4.3 WebSocket `GET ws(s)://host/kds/ws`

- Query: `max_rows` (optional, same as HTTP).
- Store: header **`x-store-id`** (lowercase in browsers) **or** query **`?store_id=<numeric>`**.

**First message:**

```json
{ "type": "SNAPSHOT", "payload": { ...same JSON as GET /kds/board... } }
```

**Later messages:** JSON **string** (text frame):

```json
{ "type": "BOARD_REFRESH", "payload": { "reason": "line_status", "store_id": 1 } }
```

Filter client-side if `payload.store_id` does not match your store.

---

## 5. TMS — HTTP + SSE

### 5.1 `GET /tms/snapshot`

Same store rules (`X-Store-Id`). Returns **tokens** (paid orders with at least one line not `COLLECTED`).

**Example:**

```json
{
  "store_id": 1,
  "live_window_minutes": 30,
  "option": "B",
  "tokens": [
    {
      "kot_code": "KTR-7",
      "order_id": "KTR-A1B2C3D4",
      "created_at": "2026-04-30T10:00:00+00:00",
      "lines": [
        {
          "id": 501,
          "item_name": "Idli",
          "quantity": 3,
          "items_need_be_ready": 1,
          "items_need_be_collected": 2,
          "order_status": "PREPARING"
        }
      ],
      "flags": {
        "has_ready_for_pickup": true,
        "has_in_kitchen": true
      }
    }
  ]
}
```

**`flags` (for headline UI):**

- **`has_ready_for_pickup`**: any line has `items_need_be_collected > 0` **or** `order_status === "READY"`.
- **`has_in_kitchen`**: any line has `items_need_be_ready > 0` **or** status is `NOT_ACCEPTED` / `PREPARING`.

### 5.2 `GET /tms/stream` (SSE)

Browsers often cannot set headers on `EventSource`; use:

```text
GET /tms/stream?store_id=1
```

First `data:` line is a JSON envelope:

```json
{"type":"SNAPSHOT","payload":{ ...same as GET /tms/snapshot... }}
```

Later events: `BOARD_REFRESH`, `ITEM_STATUS_CHANGED`, `TMS_ANNOUNCE` — same shapes as KDS WS (see §6).

### 5.3 Voice (`TMS_ANNOUNCE`)

When KDS PATCH is **`READY`** (full or partial batch), server may emit:

```json
{
  "type": "TMS_ANNOUNCE",
  "payload": {
    "store_id": 1,
    "line_id": 501,
    "order_id": "KTR-A1B2C3D4",
    "kot_code": "KTR-7",
    "item_name": "Idli",
    "quantity": 2,
    "items_need_be_ready": 1,
    "items_need_be_collected": 2,
    "order_status": "PREPARING",
    "speech": "Token number 7. Idli is ready for pickup. Please collect from the counter."
  }
}
```

Use `payload.speech` with **`SpeechSynthesisUtterance`** (browser may require a user gesture before first speak).

---

## 6. Redis event contract (KDS WS + TMS SSE)

Envelope: `{ "type": string, "payload": object }`.

| `type` | When | Payload highlights |
|--------|------|---------------------|
| **`BOARD_REFRESH`** | Payment completed for store, or any KDS line update | `reason`, `store_id`; may include `order_id`, `kot_code` on payment |
| **`ITEM_STATUS_CHANGED`** | After successful PATCH | `line_id`, `order_id`, `kot_code`, `item_name`, **`quantity` (batch)**, counters, `order_status` |
| **`TMS_ANNOUNCE`** | Same PATCH when `status` is **`READY`** | Above + **`speech`** |

**Client strategy:** on `BOARD_REFRESH` or `ITEM_STATUS_CHANGED`, either **refetch** `/kds/board` or `/tms/snapshot`, or **patch local state** by `line_id` using payload fields.

---

## 7. Frontend adoption checklist

### KDS

1. Render each line with: **ordered** `quantity`, progress **`items_need_be_ready`**, pickup queue **`items_need_be_collected`**, badge `order_status`.
2. Chef actions call **`PATCH`** with optional **`quantity`** for partial steps.
3. Subscribe to **`/kds/ws`**; on `SNAPSHOT` replace state; on `BOARD_REFRESH` / `ITEM_STATUS_CHANGED` refetch or merge.
4. Remember PATCH response **`quantity`** = **this batch**, not line total.

### TMS

1. Use **`GET /tms/snapshot`** for first paint; **`items_need_be_collected`** drives “pick up now” UI per line.
2. Use **`flags`** for header chips (“In kitchen” / “Ready”).
3. **`EventSource`** on `/tms/stream?store_id=`; handle same event types as KDS.
4. On `TMS_ANNOUNCE`, play **`speech`** and highlight `kot_code` / line.

---

## 8. curl quick reference

```bash
export BASE=http://localhost:8000
export STORE=1

curl -sS -H "X-Store-Id: $STORE" "$BASE/kds/board?max_rows=20" | jq .

curl -sS -H "X-Store-Id: $STORE" "$BASE/tms/snapshot" | jq .

curl -sS -X PATCH "$BASE/kds/items/501/status" \
  -H "X-Store-Id: $STORE" \
  -H "Content-Type: application/json" \
  -d '{"status":"READY","quantity":2}' | jq .
```

---

## 9. Order create (kiosk) — `order_type` reminder

`POST /orders/` body must include **`order_type`**: `"DINEIN"` or `"TAKEAWAY"` so KDS can show dine-in vs takeaway on the board. See `app/db/schemas/order.py` and OpenAPI `/docs`.

---

*This guide matches `app/kds/service.py`, `app/kds/router.py`, `app/kds/schemas.py`, `app/tms/service.py`, and `app/services/order_service.py` at the time of writing. For authoritative request/response schemas, use **`/docs`**.*
