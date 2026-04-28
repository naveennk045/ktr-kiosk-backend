# KDS & TMS — Backend runbook and frontend client guide

This document covers **how to run the API** and **everything frontend developers need** to build the **Kitchen Display System (KDS)** and **Token Management System (TMS)** clients against this server.

---

## Part 1 — Running the backend

### 1.1 Prerequisites

| Dependency | Role |
|------------|------|
| **PostgreSQL** | Source of truth: `stores`, `orders`, `order_items`, payments, Petpooja credentials per store, etc. |
| **Redis** | Required for live fan-out (`PUBLISH` + optional `XADD` stream). If Redis fails at startup, the app may still boot but **KDS WebSocket / TMS SSE will not receive live events** (see `app/main.py` lifespan). |
| **Python 3.10+** | Runtime |

### 1.2 Environment file

Configuration is loaded from **`.env.local`** at the project root (see `app/core/config.py`).

Minimum variables for the **Settings** model (shared infra + PhonePe API paths):

- `POSTGRES_DB_URL` — async URL, e.g. `postgresql+asyncpg://user:pass@host:5432/dbname`
- `REDIS_HOST` — full Redis URL for `redis.from_url()`, e.g. `redis://localhost:6379/0`
- `PHONEPE_BASE_URL`
- `PHONEPE_CALLBACK_URL`
- `PHONEPE_QR_INIT_ENDPOINT`
- `PHONEPE_TRANSACTION_ENDPOINT`

Per-store secrets (Petpooja, PhonePe merchant/salt, Pine Labs, etc.) are stored in **PostgreSQL**, not in this env file.

### 1.3 Database and bootstrap

1. Create an empty database and set `POSTGRES_DB_URL`.
2. On first startup, `Base.metadata.create_all` runs in the app lifespan and creates tables.
3. `ensure_default_store` runs once after migrations (`app/main.py`) — you need at least one **active** store row for kiosk flows and for **`X-Store-Id`** resolution.

If you use SQL migration scripts under `scripts/`, apply them in the order your deployment process requires (store credentials, `order_items`, etc.).

### 1.4 Install and run

```bash
cd /path/to/kiosk-server-petpooja
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# If import errors mention pydantic-settings:
pip install pydantic-settings
```

**Development:**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Sanity checks**

- `GET /` — welcome JSON  
- `GET /docs` — OpenAPI UI  
- `GET /kds/health` with header `X-Store-Id: 1` (or your store code)  
- `GET /tms/health` with same header  
- Redis: startup logs should show a successful ping when Redis is reachable  

### 1.5 CORS

`CORSMiddleware` allows all origins in code; adjust in `app/main.py` for production if needed.

### 1.6 Multi-store rule (KDS / TMS)

Almost all KDS and TMS HTTP routes require **`X-Store-Id`**: either the **numeric** primary key of `stores.id` or the **`store_code`** string (e.g. `STORE-001`). Inactive stores return **404**.

---

## Part 2 — Domain model (what the UI represents)

### 2.1 Orders and lines

- Each **order** has a business id `order_id`, a **KOT** display code `kot_code` (e.g. `KTR-42`), and belongs to **`store_id`**.
- **Lines** live in **`order_items`**: one row per item line with `item_skuid`, `item_name`, `quantity`, `price`, optional `variation_id`, `addon_items` (JSON).
- **Kitchen progress is per line**, field **`order_status`** (enum **`OrderItemStatus`**):

| Value | Typical meaning for UI |
|-------|-------------------------|
| `NOT_ACCEPTED` | Ticket line exists; kitchen has not “accepted” it yet (or default after order creation). |
| `PREPARING` | Food is being prepared. |
| `READY` | Ready for customer pickup (TMS should highlight + optional voice). |
| `COLLECTED` | Customer picked up; line is done. |

**Server rule:** status can only move **forward** along the chain (no backward transitions).

### 2.2 When does an order appear on KDS / TMS?

- **Payment** must be **`COMPLETED`**. Until then, the order is not on the kitchen/token board queries.
- **KDS board** uses **Option B** (`LIVE_ORDERS_WINDOW_MINUTES`, default **30** in `app/kds/constants.py`):
  - Include orders whose `created_at` is within the rolling window **or**
  - Include older orders if **any** line is **not** `COLLECTED` (“sticky” incomplete tickets).
- **TMS snapshot** only lists tokens (orders) where **at least one line** is **not** `COLLECTED`. When **all** lines are `COLLECTED`, the token **disappears** from TMS.

### 2.3 Clubbed totals (KDS only)

`GET /kds/board` returns **`clubbed_totals`**: sum of `quantity` by `item_name` across **visible** orders on the board, counting only lines where `order_status != COLLECTED`.

---

## Part 3 — End-to-end flow (backend + client mental model)

```mermaid
sequenceDiagram
    participant Kiosk
    participant API
    participant PG as PostgreSQL
    participant Redis
    participant KDS as KDS client
    participant TMS as TMS client

    Kiosk->>API: POST /orders/ (X-Store-Id)
    API->>PG: order + order_items (NOT_ACCEPTED)
    Kiosk->>API: Payment completes
    API->>PG: payment_status = COMPLETED
    API->>Redis: PUBLISH BOARD_REFRESH (store_id, kot_code, ...)
    API->>PG: sync Petpooja (order_service)
    KDS->>API: WS /kds/ws or GET /kds/board
    API->>KDS: snapshot + live events
    TMS->>API: GET /tms/stream or GET /tms/snapshot
    API->>TMS: tokens + events
    KDS->>API: PATCH /kds/items/{line_id}/status
    API->>PG: update order_status
    API->>Redis: ITEM_STATUS_CHANGED, TMS_ANNOUNCE if READY, BOARD_REFRESH
    TMS->>TMS: SpeechSynthesis on TMS_ANNOUNCE.speech
```

1. Kiosk creates an order → **`order_items`** rows exist (initial **`NOT_ACCEPTED`**).
2. Customer pays → **`payment_status = COMPLETED`** → server emits **`BOARD_REFRESH`** on Redis.
3. KDS/TMS clients either **poll** `GET /kds/board` / `GET /tms/snapshot` or stay on **WebSocket / SSE** and react to **`BOARD_REFRESH`** (usually refetch snapshot or merge deltas).
4. Chef updates a line → **`PATCH /kds/items/{id}/status`** → DB update → Redis events (**`ITEM_STATUS_CHANGED`**, optional **`TMS_ANNOUNCE`** with **`speech`**).

---

## Part 4 — KDS frontend client

**Base path:** `/kds`  
**Store:** send **`X-Store-Id`** on every HTTP request (numeric id or `store_code`).

### 4.1 HTTP endpoints

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| GET | `/kds/health` | `max_rows` optional (1–100, default 20) | Meta: `live_window_minutes`, etc. |
| GET | `/kds/board` | `max_rows` optional | Full snapshot for the store: orders + lines + `clubbed_totals`. |
| PATCH | `/kds/items/{line_id}/status` | — | Body JSON: `{ "status": "<OrderItemStatus>" }`. |

**PATCH body** (`KdsLineStatusPatch`):

```json
{ "status": "PREPARING" }
```

Allowed **`status`** values: `NOT_ACCEPTED`, `PREPARING`, `READY`, `COLLECTED` — must be **strictly forward** from the current row state.

**PATCH success response** (shape from `KdsBoardService.set_line_item_status`): includes `store_id`, `line_id`, `order_id`, `kot_code`, `item_name`, `quantity`, `order_status`.

### 4.2 `GET /kds/board` response shape (conceptual)

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
      "order_id": "KTR-AB12CD34",
      "kot_code": "KTR-5",
      "kot_number": 5,
      "kot_date": "2026-04-18",
      "created_at": "2026-04-18T10:00:00+00:00",
      "lines": [
        {
          "id": 501,
          "sku_code": "SKU123",
          "item_name": "Masala Dosa",
          "quantity": 2,
          "order_status": "PREPARING"
        }
      ]
    }
  ],
  "clubbed_totals": [
    { "item_name": "Masala Dosa", "quantity": 2 }
  ]
}
```

Orders are ordered **oldest first** (`created_at` ascending). Only orders that match Option B and **`payment_status = COMPLETED`** are returned, up to **`max_rows`** KOT cards.

### 4.3 WebSocket — `GET ws(s)://host/kds/ws`

**Query**

- `max_rows` (optional, 1–100, default 20) — same meaning as HTTP board.

**Store identification (required)**

1. Preferred: header **`x-store-id`** (browsers send WebSocket subrequest headers in lowercase).
2. Fallback: query **`?store_id=<numeric>`** (useful if you cannot set headers).

**First message from server**

JSON object:

```json
{ "type": "SNAPSHOT", "payload": { ... same shape as GET /kds/board ... } }
```

**Subsequent messages**

Each message is a **JSON string** (text frame) with shape:

```json
{
  "type": "<EVENT_TYPE>",
  "payload": { }
}
```

The server **filters** messages: if `payload.store_id` is present and does **not** match the connected store, the message is **not** forwarded to that socket.

**If Redis is unavailable**

The socket still opens and sends **`SNAPSHOT`**, then periodic **`{ "type": "PING", "payload": {} }`** JSON messages; there is **no** live pub/sub.

### 4.4 KDS client implementation checklist

1. On load: **`GET /kds/board?max_rows=N`** with `X-Store-Id` (or open **WebSocket** and render first `SNAPSHOT`).
2. Subscribe to WS and `JSON.parse` each text message; handle types in section 6.
3. On **`BOARD_REFRESH`**: refetch **`GET /kds/board`** or merge if you maintain local state.
4. Chef taps: **`PATCH /kds/items/{line.id}/status`** with the next `OrderItemStatus`.
5. Show **`clubbed_totals`** as a sidebar or footer row.
6. Fallback if WS fails: poll **`GET /kds/board`** every N seconds.

---

## Part 5 — TMS frontend client

**Base path:** `/tms`  
**Store:** **`X-Store-Id`** on HTTP routes where `get_store_context` is used.

### 5.1 HTTP endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/tms/health` | Meta (`live_window_minutes`, etc.). |
| GET | `/tms/snapshot` | All active tokens for the store (SSR-friendly). |

### 5.2 `GET /tms/snapshot` response shape (conceptual)

```json
{
  "store_id": 1,
  "live_window_minutes": 30,
  "option": "B",
  "tokens": [
    {
      "kot_code": "KTR-5",
      "order_id": "KTR-AB12CD34",
      "created_at": "2026-04-18T10:00:00+00:00",
      "lines": [
        {
          "id": 501,
          "item_name": "Masala Dosa",
          "quantity": 2,
          "order_status": "READY"
        }
      ],
      "flags": {
        "has_ready_for_pickup": true,
        "has_in_kitchen": false
      }
    }
  ]
}
```

**`flags`**

- `has_ready_for_pickup` — at least one line in **`READY`**.
- `has_in_kitchen` — at least one line in **`NOT_ACCEPTED`** or **`PREPARING`**.

Tokens **omit** orders where every line is **`COLLECTED`**.

### 5.3 Server-Sent Events — `GET /tms/stream`

**Store identification**

Uses **`get_store_context_flexible`**:

- Header **`X-Store-Id`**, **or**
- Query **`?store_id=<numeric>`** (recommended for **`EventSource`**, which cannot set custom headers in the browser).

Example:

```text
GET /tms/stream?store_id=1
```

**First SSE `data:` line**

Wrapped JSON (your client should `JSON.parse` after stripping the `data: ` prefix or use the EventSource `message` event `data` string):

```json
{"type":"SNAPSHOT","payload":{ ... same as GET /tms/snapshot ... }}
```

**Later `data:` lines**

Same envelope as WebSocket: `{ "type": "...", "payload": { ... } }`.  
Server filters by **`payload.store_id`** when present.

**Keep-alives**

Lines starting with **`:`** (comments) are pings; ignore them.

**If Redis is unavailable**

Only snapshot + periodic ping comments; no live kitchen events.

### 5.4 Voice (browser)

When **`type === "TMS_ANNOUNCE"`**, read **`payload.speech`** (plain English string) and pass it to **`SpeechSynthesisUtterance`** (user gesture may be required on some browsers before the first speak).

Typical trigger: line moved to **`READY`** on the KDS (server generates speech server-side text only; **audio is produced in the browser**).

### 5.5 TMS client implementation checklist

1. First paint: **`GET /tms/snapshot`** with `X-Store-Id`.
2. Live updates: **`new EventSource(base + '/tms/stream?store_id=' + storeId)`** (or fetch-stream if you proxy with headers).
3. On each message: parse JSON; if `type === 'SNAPSHOT'`, replace state; if `BOARD_REFRESH`, refetch snapshot or wait for next announce; if `ITEM_STATUS_CHANGED`, patch local token lines; if `TMS_ANNOUNCE`, play **`payload.speech`** and flash the token/line.
4. Hide tokens that disappear from the next snapshot (all lines **`COLLECTED`**).

---

## Part 6 — Redis event contract (shared by KDS WS and TMS SSE)

All events are JSON: `{ "type": string, "payload": object }`.

| `type` | When | `payload` (important keys) |
|--------|------|------------------------------|
| `BOARD_REFRESH` | New payment completed for a store, or any line status change from KDS | `reason`, **`store_id`** (always set when emitted from this server), `order_id`, `kot_code` on payment; line updates use `reason: "line_status"`. Clients usually **refetch** board/snapshot. |
| `ITEM_STATUS_CHANGED` | After successful PATCH line status | `store_id`, `line_id`, `order_id`, `kot_code`, `item_name`, `quantity`, `order_status` |
| `TMS_ANNOUNCE` | Line moved to **`READY`** | Same as `ITEM_STATUS_CHANGED` plus **`speech`** (string for TTS) |

**Durability:** the server also **`XADD`**s the same JSON string to Redis stream key **`kds:stream`** (for ops/debug/replay); clients normally use **pub/sub** only via WS/SSE.

---

## Part 7 — Error handling and HTTP status codes

| Code | Typical cause |
|------|----------------|
| 400 | Invalid status transition, missing store identifier on flexible routes |
| 404 | Store unknown/inactive, or line not found / not in this store |
| 503 | Redis not configured when an endpoint **Depends** on `get_redis_client` |

**WebSocket:** missing store id → connection closed with code **4400**. Snapshot failure → **1011**.

**Live updates vs polling:** Redis pub/sub drives the WebSocket/SSE stream. If the tab **closes the socket** or navigates away, the server stops pushing to that connection (this is normal, not a server bug). Keep the WebSocket open while the KDS page is visible, and on each incoming message `JSON.parse` the text and handle `BOARD_REFRESH` / `ITEM_STATUS_CHANGED` / `TMS_ANNOUNCE`. Petpooja **403** on `save_order` does **not** block Redis events: **`BOARD_REFRESH`** is still emitted when payment completes; line **`PATCH`** still emits kitchen events.

**Shutting down uvicorn while SSE/WS clients are connected:** Stopping the process cancels in-flight tasks (Redis `get_message`, `yield` to the client, Starlette’s disconnect watcher). That produces **`asyncio.CancelledError`** internally; the app code closes Redis pub/sub in `finally` and **does not treat that as a business failure**. If you still see a lifespan `CancelledError` trace on **double Ctrl+C** or force-kill, that is the ASGI server aborting the lifespan handshake—prefer **one** Ctrl+C and wait for “Application shutdown complete” before starting again.

---

## Part 8 — Quick reference (curl)

Replace `BASE` and store id.

```bash
curl -sS -H "X-Store-Id: 1" "http://localhost:8000/kds/board?max_rows=10"
curl -sS -H "X-Store-Id: 1" "http://localhost:8000/tms/snapshot"
curl -sS -X PATCH "http://localhost:8000/kds/items/501/status" \
  -H "X-Store-Id: 1" -H "Content-Type: application/json" \
  -d '{"status":"READY"}'
```

---

## Part 9 — Related docs in this repo

- `docs/API.md` — general kiosk API and `X-Store-Id` conventions  
- `docs/docker_droplet.md` — deployment notes if you use Docker/droplets  

For **dashboard** admin UI (order grid, not KDS), see `docs/dashboard_api.md` and `docs/frontend_dashboard_guide.md`.

---

*Generated from the codebase in `app/kds`, `app/tms`, `app/services/payment_service.py`, and `app/db/models/order.py`. If behaviour changes, prefer OpenAPI at `/docs` as the live contract.*
