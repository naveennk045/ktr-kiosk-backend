# Kitchen & Token Displays — API Reference and Feature Guide

APIs for the **KDS** (kitchen display) and the **TMS** token board (customer TV), the live event
stream they share, and what the board does with it.

- Architecture and technical design: [`TMS-architecture.md`](TMS-architecture.md)
- Every other endpoint: [`API.md`](API.md) · live schemas at `GET /docs`

---

## Quick start

```bash
# Backend (needs PostgreSQL + Redis; see .env.example)
python run.py                     # http://localhost:8000 (Procfile uses 8080 in production)

# Board (tms-client repo)
echo "VITE_API_BASE_URL=http://localhost:8000" > .env
npm install && npm run dev        # http://localhost:5173
```

Open `/setup` once on the TV and pick the outlet (saved in `localStorage`), then `/tms`.

## Conventions

| Topic | Detail |
|-------|--------|
| Store scoping | `X-Store-Id` header: numeric `stores.id` or `store_code`. Missing → `400`, unknown/inactive → `404`. |
| SSE / browser `EventSource` | Can't send headers, so `/tms/stream` also accepts `?store_id=`. |
| Timestamps | ISO 8601 with timezone (UTC from the server). |
| Token number | Daily per store (`kot_number`), shown as `101`; `kot_code` is `KTR-101`. |
| Events | JSON `{"type": "<EVENT>", "payload": {..., "store_id": N}}` on SSE (`data:` lines) and WebSocket (text frames). |

---

## TMS — token board (`/tms`)

| Method | Path | Store | Description |
|--------|------|-------|-------------|
| `GET` | `/tms/health` | `X-Store-Id` | Service name and live window. |
| `GET` | `/tms/snapshot` | `X-Store-Id` | Every token on the board, with board state, lines and day stats. Cached per store in Redis. |
| `GET` | `/tms/menu-meta` | — | Hard-coded dish copy, categories, milestone groups, ticker and story reel. Same for every store. |
| `GET` | `/tms/stream` | `X-Store-Id` or `?store_id=` | Server-Sent Events: a `SNAPSHOT` first, then every kitchen event for the store. |

### `GET /tms/snapshot`

```http
GET /tms/snapshot
X-Store-Id: 1
```

```json
{
  "store_id": 1,
  "live_window_minutes": 30,
  "option": "B",
  "server_time": "2026-11-06T09:45:10.717960+00:00",
  "stats": {
    "orders_today": 51,
    "category_counts": { "davangere": 24, "coffee": 30, "rice": 9 },
    "on_board": 6
  },
  "tokens": [
    {
      "kot_code": "KTR-50",
      "token_number": "50",
      "order_id": "ORD-8F2K1",
      "order_type": "TAKEAWAY",
      "board_state": "partial",
      "display_state": "READY",
      "milestone": "50th order of the day",
      "created_at": "2026-11-06T09:44:31+00:00",
      "lines": [
        {
          "id": 5,
          "item_name": "Benne Masala Dose",
          "quantity": 2,
          "items_need_be_ready": 0,
          "items_need_be_collected": 2,
          "order_status": "READY",
          "preparing_at": "2026-11-06T09:44:33+00:00",
          "ready_at": "2026-11-06T09:48:02+00:00",
          "has_addons": true,
          "menu_id": "dv-masala",
          "category": "davangere",
          "image": "dav",
          "short": "With potato palya, roasted in benne.",
          "first_of_day": true
        }
      ],
      "flags": { "has_ready_for_pickup": true, "has_in_kitchen": true }
    }
  ]
}
```

**Which tokens:** paid orders for the store with at least one line not `COLLECTED`, oldest first,
up to 200.

**Token fields**

| Field | Type | Meaning |
|-------|------|---------|
| `token_number` | string | Short number for display (`kot_number`). |
| `order_type` | `DINEIN` \| `TAKEAWAY` | Shown as Dine-in / Parcel. |
| `board_state` | `received` \| `cooking` \| `partial` \| `ready` | Card state (rules in the architecture doc §4). |
| `display_state` | `READY` \| `PREPARING` | Legacy two-column state: `READY` if any portion waits at the counter. |
| `milestone` | string \| null | `"50th order of the day"` on every 50th token. |
| `flags` | object | Legacy: any portion ready / any portion still in the kitchen. |

**Line fields**

| Field | Type | Meaning |
|-------|------|---------|
| `items_need_be_ready` | int | Portions still cooking. |
| `items_need_be_collected` | int | Portions ready, waiting at the counter. |
| `order_status` | `NOT_ACCEPTED` \| `PREPARING` \| `READY` \| `COLLECTED` | Derived line status. |
| `preparing_at` / `ready_at` | timestamp \| null | Kitchen start; last portion ready. `null` for lines from before the migration. |
| `order_type` | `DINEIN` \| `TAKEAWAY` | This line's effective type (mixed orders can have take-away lines in a dine-in token). |
| `has_addons` | bool | Petpooja add-ons/customisations present ("Made your way" tag). |
| `menu_id`, `category`, `image`, `short` | string \| null | Match against the hard-coded menu; all `null` if the item name isn't in it. |
| `first_of_day` | bool | This token is today's first order of this dish. |

**Stats:** counted from today's paid orders (`kot_date` = server's today). `category_counts` are units
ordered per menu category.

**Caching:** built once per kitchen change and shared via Redis (see architecture §5.2). `server_time`
is always fresh, so clients can correct for TV clock drift.

### `GET /tms/menu-meta`

```json
{
  "categories": [
    { "id": "davangere", "stage": "On the tawa", "name": "Davangere Benne Dose",
      "short": "Davangere", "image": "dav", "fact": "Benne means butter in Kannada. …" }
  ],
  "items": [
    { "id": "dv-masala", "category": "davangere", "name": "Benne Masala Dose", "image": "dav",
      "short": "With potato palya, roasted in benne.",
      "lead": "Soft inside, crisp outside, roasted in benne and filled with potato palya.",
      "pitch": "the dose Davangere is famous for. …",
      "fact": "Benne means butter in Kannada. …",
      "signature": true, "traditional": true, "aliases": [] }
  ],
  "groups": { "coffee": { "one": "filter coffee", "many": "filter coffees", "image": "coffee" } },
  "served_step": 50,
  "ticker": [ { "k": "Benne", "t": "means butter in Kannada. Our Davangere Dose is roasted in it." } ],
  "reel": [ { "image": "store", "kicker": "Welcome to KTR",
              "title": "A Bengaluru tiffin room in Versova", "body": "Hand-poured filter coffee, …" } ]
}
```

- `image` is a key; the board loads `/img/<key>.jpg` from its own static files. `null` → plaid placeholder.
- `options` on categories and items: free-text kitchen options the kiosk offers ("Extra benne", "Less spicy").
- Kitchen stages: Davangere and Bengaluru doses *On the tawa*, idlis *Steaming*, vadas *Frying*,
  rice and desserts *In the pot*, coffee *Brewing*, add-ons *Plating*.
- To support a Petpooja name that doesn't match, add it to that dish's `aliases` in
  `app/tms/menu_meta.py`.

### `GET /tms/stream` (SSE)

```http
GET /tms/stream?store_id=1
Accept: text/event-stream
```

```
data: {"type":"SNAPSHOT","payload":{ …same as /tms/snapshot… }}

data: {"type":"BOARD_REFRESH","payload":{"reason":"line_status","store_id":1}}

: ping
```

- The first message is always `SNAPSHOT`. After that, every `kds:notify` event for this store is
  forwarded as-is.
- `: ping` comments every 25 s when idle keep proxies from closing the connection.
- If Redis drops, the server resubscribes with backoff (1 s → 10 s). If Redis is unavailable at
  startup, the stream only sends pings.

---

## Events

| Type | Sent by | When | Payload |
|------|---------|------|---------|
| `SNAPSHOT` | SSE / WS on connect | Once, first message | Full snapshot (TMS) or board (KDS). |
| `BOARD_REFRESH` | Payments, KDS | Order paid; any line status change | `store_id`, `reason` (`payment_completed` · `line_status`), plus `order_id`, `kot_code` on payment. **Refetch the snapshot.** |
| `ITEM_STATUS_CHANGED` | KDS | Any line status change (always followed by `BOARD_REFRESH`) | Line payload (below). |
| `TMS_ANNOUNCE` | KDS | Line moved to `READY`, or staff re-announce | Line payload + `speech`. Whole-order re-announce sends only `store_id`, `order_id`, `kot_code`, `speech`. |
| `TMS_MILESTONE` | KDS | A READY move took today's served count for a dish or group past a multiple of 50 | Milestone payload (below). |
| `PING` | KDS WebSocket | Every 30 s when Redis is unavailable | `{}` |

**Line payload** (`ITEM_STATUS_CHANGED`, `TMS_ANNOUNCE`)

```json
{ "store_id": 1, "line_id": 5, "order_id": "ORD-8F2K1", "kot_code": "KTR-50",
  "item_name": "Hot Filter Coffee", "quantity": 1,
  "items_need_be_ready": 0, "items_need_be_collected": 1, "order_status": "READY",
  "speech": "Token number 50. Hot Filter Coffee is ready for pickup. Please collect from the counter." }
```

`quantity` is the number of portions moved by this change, not the line total.

**Milestone payload** (`TMS_MILESTONE`)

```json
{ "store_id": 1, "order_id": "ORD-8F2K1", "kot_code": "KTR-52", "token_number": "52",
  "n": 100, "one": "filter coffee", "many": "filter coffees", "image": "coffee",
  "menu_id": "cf-hot", "group": true }
```

At most two per change, group milestones first (e.g. "100th filter coffee" before "100th Hot Filter
Coffee"). Groups: doses, idli plates, vada plates, rice dishes, Kesari Bath, filter coffees.

---

## KDS — kitchen display (`/kds`)

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `GET` | `/kds/health` | — | Service name and live window. |
| `GET` | `/kds/board?max_rows=20` | — | Live orders (last 30 min, or older but unfinished) with lines, plus `clubbed_totals` (units per item still open). `max_rows` 1–100. |
| `PATCH` | `/kds/items/{line_id}/status` | `{"status": "...", "quantity": n?}` | Move a line forward. |
| `POST` | `/kds/items/{line_id}/announce` | — | Re-announce one line on the board. |
| `POST` | `/kds/orders/{order_pk}/announce` | — | Re-announce a whole token (`order_pk` is `orders.id`). |
| `WS` | `/kds/ws?store_id=1&max_rows=20` | — | `SNAPSHOT` (board), then every kitchen event as JSON text. |

All need `X-Store-Id` (the WebSocket accepts `?store_id=`).

### `PATCH /kds/items/{line_id}/status`

```json
{ "status": "READY", "quantity": 1 }
```

| `status` | Effect | `quantity` |
|----------|--------|-----------|
| `PREPARING` | Marks the line as cooking; sets `preparing_at` once. | ignored |
| `READY` | Moves portions from cooking to the counter; sets `ready_at` when none are left cooking. Sends `TMS_ANNOUNCE` and, if crossed, `TMS_MILESTONE`. | ≤ `items_need_be_ready` (default: whole line) |
| `COLLECTED` | Removes portions from the counter. | ≤ `items_need_be_collected` (default: whole line) |

Errors: `404` line not in this store · `400` order not paid, moving back to `NOT_ACCEPTED`, or
`quantity` over the allowed count. Response: the line payload above.

---

## Token board features (tms-client)

### Layout

| Area | What it shows |
|------|---------------|
| **Header** | KTR logo, outlet, Orders today, Davangere Doses, On the board, clock (server-corrected), Announcements, language, Full screen, Setup. |
| **Order status** | One card per token: number, state, time since order, Dine-in/Parcel, tags, each item with stage and timer, progress bar or "Please collect at the counter · Ready in m:ss". |
| **Spotlight** | Dish photo, kicker, title and a typed-out story. "Just ordered" for new tokens (held 25 s); otherwise rotates signature and traditional dishes every 14 s. |
| **Ticker** | Karnataka food facts scrolling along the bottom. |

### Card tags (max three)

| Tag | Rule |
|-----|------|
| ★ *100th filter coffee served!* | This token triggered a served milestone (from `TMS_MILESTONE`). |
| ★ *50th order of the day* | `milestone` from the snapshot. |
| *First Benne Open Dose of the day* | A line has `first_of_day`. |
| *Feast mode: 6 dishes* | 5+ non-add-on units. |
| *Karnataka classic: Medu Wada* | A traditional rice, vada or dessert dish, or Temple Puliyogare (when fewer than two tags so far). |
| *Made your way* | A line has Petpooja add-ons (when fewer than two tags so far). |

### Live moments

| Moment | Trigger | What guests see/hear |
|--------|---------|----------------------|
| New token | Token appears in a snapshot | Card pops in · toast "Token 51 · 2 × Medu Wada" with a dish fact · "Just ordered" spotlight |
| Part ready | Card becomes `partial` | Yellow toast "part of your order is ready", ready items tick green |
| Ready | Card becomes `ready` | Card flips to orange with confetti · toast · chime + voice from `TMS_ANNOUNCE` |
| Reminder | Still `ready` 2 minutes later | One more toast and voice call ("a gentle reminder") |
| Called again | Staff re-announce (`TMS_ANNOUNCE`) | Toast "Calling token 51" + voice |
| Completed | Token leaves the snapshot | Green "Completed in 7:24 · Kitchen time 6:56" for 9 s |
| Milestone | `TMS_MILESTONE` | Full-screen flash: photo, count-up to "100th", "Filter Coffees Served Today", rays, confetti, voice |
| Empty board | No tokens on the board for 15 s | Full-screen story reel (12 slides). Closes the moment a token appears; tapping shows the empty board and the reel returns after 15 s |

### Interaction

- **Filters:** All · Being made · Ready.
- **Find my token:** type a number → that card is outlined and scrolled into view, or "Not on the board".
- **Tap a card:** details popup with timeline (received, in the kitchen, ready, collected), every
  item with its stage and short description, and a "Did you know?" fact. Esc or tap outside to close.
- **Busy board:** cards page every 8 s without being cut in half ("Page 2 of 4"); ready tokens sort
  first so they're always on page 1. Paging pauses while searching or with a popup open.

### Announcements

- Tap **Announcements** once (browsers only allow audio after a tap); the button turns yellow.
- A chime plays before every call; a brighter one for milestones.
- Voice: prefers an Indian English voice (e.g. Neerja, Prabhat, Heera, Ravi), then British/US English.
- Language button cycles **English → English + हिंदी → हिंदी** (saved on the TV). Without a Hindi
  voice installed, the Hindi line is read in romanised text by the English voice.

### Client storage

| Key | Value |
|-----|-------|
| `ktr_tms_store_context` | Selected outlet `{storeId, storeCode, storeName, savedAt}` |
| `ktr_tms_announce_lang` | `en` \| `hi` \| `both` |

### Display

Landscape TV first. Scales ×1.4 on full-HD and ×2 on 4K. On the Amazon Silk browser (Fire TV) the
first touch or key press requests full screen.

---

## Frontend checklist

- [ ] `VITE_API_BASE_URL` points at the backend (no trailing slash).
- [ ] TV opened `/setup` once and picked the outlet.
- [ ] Announcements tapped on after every TV restart (browser audio unlock).
- [ ] Real Petpooja item names show photos and tags; add `aliases` in `menu_meta.py` for any that don't.
- [ ] Migration run on each primary cluster before deploying the backend.
