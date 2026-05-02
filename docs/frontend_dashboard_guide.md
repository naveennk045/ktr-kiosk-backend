# Admin dashboard — frontend developer guide

This document is for anyone building the **admin analytics UI** against the KTR kiosk backend. It includes **realistic request/response samples**, a **walkthrough of how to wire the UI**, **modern dashboard UX guidance**, and a **ready-to-paste brief** you can hand to a designer or another engineer.

**Related**: concise API tables live in [`dashboard_api.md`](./dashboard_api.md).

---

## 1. Base URL and conventions

| Item | Value |
|------|--------|
| Default dev server | `http://localhost:8000` (see `run.py`) |
| API style | REST, JSON |
| CORS | `allow_origins=["*"]` — fine for dev; lock down in production |
| Date windows | **Asia/Kolkata (IST)** for `period` filters |
| Analytics scope | **`/analytics/summary` counts only `payment_status === "COMPLETED"`** orders. Pending or failed payments do not affect KPI totals. |
| Order list scope | **`GET /orders`** filters by `created_at` in the chosen `period` — it includes **all** payment statuses unless you pass `status`. |

**Important for product copy**: If a kiosk order is still `PENDING`, it appears in the order grid (for the matching time range) but **not** in revenue / payment / dine-in KPIs until payment completes.

---

## 2. Endpoints the dashboard needs

| Purpose | Method | Path |
|---------|--------|------|
| KPI header (revenue, counts, payment mix) | `GET` | `/analytics/summary` |
| **Top N items by quantity** | `GET` | `/analytics/items/top` |
| **Daily item order counts** | `GET` | `/analytics/items/daily` |
| **Full item-wise summary** | `GET` | `/analytics/items/summary` |
| Paginated orders | `GET` | `/orders` |
| Single order (drawer / modal) | `GET` | `/orders/{order_id}` |

---

## 3. Query parameters

### `GET /analytics/summary`

| Param | Type | Default | Allowed values |
|-------|------|---------|----------------|
| `period` | string | `all_time` | `today`, `yesterday`, `last_week`, `all_time` |

**Meaning (IST):**

- `today` — from **today 00:00 IST** through **now**
- `yesterday` — **full previous calendar day** in IST
- `last_week` — from **00:00 seven days ago** IST through **now** (rolling 7 days)
- `all_time` — no lower date bound

### `GET /orders`

| Param | Type | Default | Notes |
|-------|------|---------|--------|
| `period` | string | `all_time` | **Use the same value as the KPI strip** so numbers and table stay in sync |
| `page` | int | `0` | Zero-based |
| `size` | int | `20` | Page size |
| `sortBy` | string | `created_at` | `created_at` or `total_amount` |
| `sortDir` | string | `desc` | `asc` or `desc` |
| `status` | string | *(omit)* | e.g. `PENDING`, `COMPLETED`, `FAILED` |
| `search` | string | *(omit)* | Substring match on `order_id` |

### `GET /orders/{order_id}`

Path parameter is the business **`order_id`** (e.g. `KTR-1609D08171`), not the numeric DB `id`.

---

## 4. Sample API requests and responses

Below, **`BASE`** means your API origin, e.g. `http://localhost:8000`.

### 4.1 Analytics summary

**Request**

```http
GET /analytics/summary?period=today HTTP/1.1
Host: localhost:8000
Accept: application/json
```

**Example response** (`200 OK`)

```json
{
  "period": "today",
  "totalRevenue": 48250.5,
  "totalOrders": 42,
  "dineInOrders": 28,
  "takeAwayOrders": 14,
  "upiRupees": 22000,
  "cardRupees": 15000,
  "cashRupees": 11250.5
}
```

**Field notes**

- `upiRupees` — backend maps from stored payment method **`QR`** (UPI QR flow).
- `cardRupees` — **`CARD`** only.
- `cashRupees` — **`CASH` plus `MANUAL`** (single bucket in analytics).
- All monetary KPIs are **only from completed orders** in the selected period.

**Fetch (browser)**

```javascript
const period = "today";
const res = await fetch(
  `${import.meta.env.VITE_API_BASE}/analytics/summary?period=${period}`
);
const summary = await res.json();
```

---

### 4.2 Order list (paginated)

**Request**

```http
GET /orders?period=all_time&page=0&size=20&sortBy=created_at&sortDir=desc HTTP/1.1
Host: localhost:8000
Accept: application/json
```

**Example response** — includes a row shaped like your sample DB order `KTR-1609D08171` (grid uses a **short text summary** of line items, not full JSON):

```json
{
  "content": [
    {
      "orderRefId": "KTR-1609D08171",
      "orderId": "KTR-1609D08171",
      "kotCode": "KTR-1",
      "orderType": "DINEIN",
      "paymentType": null,
      "location": "Kiosk 1",
      "amount": 1142.0,
      "paymentStatus": "PENDING",
      "erpStatus": "NOT_POSTED",
      "itemsSummary": "Royal Wonder Waffles... (+1 more)",
      "createdAt": "2026-03-16T07:02:59.101211Z"
    }
  ],
  "totalPages": 1,
  "totalElements": 1
}
```

**Note on `itemsSummary`**: The server prefers each line’s **`item_name`**, then **`name`**. For a full breakdown, use **`GET /orders/{order_id}`**.

**Fetch**

```javascript
const params = new URLSearchParams({
  period: "all_time",
  page: "0",
  size: "20",
  sortBy: "created_at",
  sortDir: "desc",
});
const res = await fetch(`${import.meta.env.VITE_API_BASE}/orders?${params}`);
const grid = await res.json();
```

---

### 4.3 Order detail (full line items from DB JSON)

**Request**

```http
GET /orders/KTR-1609D08171 HTTP/1.1
Host: localhost:8000
Accept: application/json
```

**Example response** — aligned with your **sample row** (`items` mirrors what is stored in JSONB; shape may vary slightly by order version):

```json
{
  "orderRefId": "KTR-1609D08171",
  "location": "Kiosk 1",
  "amount": 1142.0,
  "paymentStatus": "PENDING",
  "erpStatus": "NOT_POSTED",
  "items": [
    {
      "quantity": 1,
      "sku_code": "10550601",
      "item_name": "Royal Wonder Waffles",
      "unit_price": 289.0
    },
    {
      "quantity": 2,
      "sku_code": "10550471",
      "item_name": "Paneer Maxican Sizzler",
      "unit_price": 399.0
    }
  ],
  "paymentMeta": null,
  "createdAt": "2026-03-16T07:02:59.101211Z"
}
```

**Rendering tip**: Line items are **not** normalized to `{ name, qty, price }` in all historical data. Defensive UI:

```typescript
function lineTitle(row: Record<string, unknown>): string {
  return String(row.item_name ?? row.name ?? "Item");
}
function lineQty(row: Record<string, unknown>): number {
  return Number(row.quantity ?? row.qty ?? 0);
}
```

---

## 5. How to implement the dashboard (recommended flow)

### 5.1 State to keep in the client

- **`period`**: `today` | `yesterday` | `last_week` | `all_time` — single source of truth for both KPIs and table.
- **`summary`**: last successful `/analytics/summary` response (or `null` while loading).
- **`orders`**: last `/orders` response (`content`, `totalPages`, `totalElements`).
- **`page`**: current page index (reset to `0` when `period` changes).
- **`selectedOrderId`**: for drawer / modal (`null` when closed).
- **`loading` / `error`**: per-section loading improves perceived performance (skeleton KPI vs table).

### 5.2 Data loading

1. On **`period`** change: set `page = 0`, then **in parallel**:
   - `GET /analytics/summary?period=...`
   - `GET /orders?period=...&page=0&size=...`
2. On **pagination** only: `GET /orders` with updated `page` (same `period`).
3. On **row click**: `GET /orders/{orderRefId}` and show side panel.

### 5.3 Error handling

- Non-200: show toast + keep last good data if you prefer sticky UX.
- Empty table: show illustration + “No orders in this range” (not an error).

### 5.4 Environment

- Use `VITE_API_BASE` / `NEXT_PUBLIC_API_BASE` (or equivalent) so dev/stage/prod only change env, not code.

---

## 6. TypeScript types (optional but helpful)

```typescript
export type DashboardPeriod = "today" | "yesterday" | "last_week" | "all_time";

export type AnalyticsSummary = {
  period: DashboardPeriod;
  totalRevenue: number;
  totalOrders: number;
  dineInOrders: number;
  takeAwayOrders: number;
  upiRupees: number;
  cardRupees: number;
  cashRupees: number;
};

export type OrderGridItem = {
  orderRefId: string;
  orderId: string;
  kotCode: string;
  orderType: "DINEIN" | "TAKEAWAY";
  paymentType: "QR" | "CARD" | "CASH" | "MANUAL" | null;
  location: string;
  amount: number;
  paymentStatus: "PENDING" | "COMPLETED" | "FAILED";
  erpStatus: string;
  itemsSummary: string;
  createdAt: string;
};

export type OrderGridResponse = {
  content: OrderGridItem[];
  totalPages: number;
  totalElements: number;
};

export type OrderDetail = {
  orderRefId: string;
  location: string;
  amount: number;
  paymentStatus: "PENDING" | "COMPLETED" | "FAILED";
  erpStatus: string;
  items: Record<string, unknown>[];
  paymentMeta: Record<string, unknown> | null;
  createdAt: string;
};

// ─── Item-wise Analytics ───────────────────────────────────────────────────────

export type ItemRankEntry = {
  sku: string;
  item_name: string;
  total_quantity: number;
  total_revenue: number;
  order_count: number;
};

export type ItemTopResponse = {
  period: DashboardPeriod;
  limit: number;
  items: ItemRankEntry[];
};

export type ItemDailyCount = {
  date: string;          // "YYYY-MM-DD" IST date
  sku: string;
  item_name: string;
  total_quantity: number;
  order_count: number;
};

export type ItemDailyResponse = {
  period: DashboardPeriod;
  sku_filter: string | null;
  rows: ItemDailyCount[];
};

export type ItemSummaryEntry = {
  sku: string;
  item_name: string;
  total_quantity: number;
  total_revenue: number;
  order_count: number;
  avg_quantity_per_order: number;
};

export type ItemSummaryResponse = {
  period: DashboardPeriod;
  total_items_sold: number;
  unique_items: number;
  items: ItemSummaryEntry[];
};
```

---

## 7. Modern UI and dashboard design guidance

Use this as a **design system brief** so the screen feels current (2025–2026 patterns), readable for ops staff, and calm under load.

### 7.1 Layout

- **Top bar**: product name, optional environment badge (`STAGING`), user menu placeholder.
- **Period control**: prominent **segmented control** or **pill tabs** for `Today | Yesterday | Last 7 days | All time` bound to `period`. Show IST hint in tooltip: “Metrics use India Standard Time.”
- **KPI row**: 2 rows max on desktop:
  - Row A: **Total revenue** (hero, largest type), **Total orders**.
  - Row B: **Dine-in** vs **Takeaway** counts; optional small **donut or stacked bar** for share.
- **Payment row**: three compact cards — **UPI**, **Card**, **Cash** (`cashRupees` includes manual-tender amounts in analytics). Use **₹** with **Indian grouping** (`en-IN`).
- **Orders table**: full width below; **sticky header**; columns include **order id**, **KOT code**, **order type**, **payment type** (when set); **right-align** money; **monospace** for order IDs.

### 7.2 Visual style

- **Spacing**: 8px grid; generous padding in KPI cards (16–24px).
- **Typography**: one sans family (e.g. Inter, DM Sans, Geist); numeric tabular lining where possible.
- **Color**: neutral background (`slate` / `zinc` 50–100); **one accent** for primary actions; **semantic chips** for payment status (amber pending, green completed, red failed).
- **Charts**: use **donut** for payment mix (UPI / Card / Cash) only when at least one value &gt; 0; otherwise show “No completed payments in this range” for KPI section. **Avoid 3D** and heavy gradients.

### 7.3 Interaction

- **Loading**: skeleton blocks for KPIs; table skeleton rows — avoid full-page spinners.
- **Detail drawer**: slide-over on desktop; full-screen sheet on mobile.
- **Pagination**: prev/next + page numbers; disable while loading.
- **Accessibility**: focus trap in drawer; sufficient contrast (WCAG AA); `aria-live` for error toasts.

### 7.4 What not to do

- Do not show **KPI revenue** and **table sum of amounts** as the same thing — table can include pending orders; KPI does not.
- Do not hardcode timezone; display times in **IST** in the UI for human-readable columns (`toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })`).

---

## 8. Copy-paste prompt for the frontend developer (or AI assistant)

You can paste the block below into a ticket or an AI chat as the build specification.

```text
Build an admin analytics dashboard for a FastAPI backend.

API base URL: configurable via environment variable (e.g. VITE_API_BASE).

Endpoints:
- GET /analytics/summary?period={today|yesterday|last_week|all_time}
  Returns completed-order KPIs only: totalRevenue, totalOrders, dineInOrders, takeAwayOrders, upiRupees, cardRupees, cashRupees (cash+manual tender). Period uses IST on the server.
- GET /analytics/items/top?period=&limit=
  Top N items by quantity sold. Returns sku, item_name, total_quantity, total_revenue, order_count.
- GET /analytics/items/daily?period=&sku=(optional)
  Per-day item counts. Each row: date (YYYY-MM-DD IST), sku, item_name, total_quantity, order_count.
  Pass sku to filter to one item for a trend line/bar chart.
- GET /analytics/items/summary?period=
  All items: total_quantity, total_revenue, order_count, avg_quantity_per_order. Top-level: total_items_sold, unique_items.
- GET /orders?period=...&page=&size=&sortBy=&sortDir=&status=&search=
  Returns paginated orders; use the SAME period as analytics so the table matches the date filter.
- GET /orders/{order_id} for a side drawer with full line items and paymentMeta.

UX:
- Segmented period control; changing period resets page to 0 and refetches all analytics + orders in parallel.
- KPI strip: revenue hero, order count, dine-in vs takeaway, payment method rupee cards; format currency in INR (en-IN).
- Item analytics section below KPIs: bestsellers bar chart (items/top), daily quantity trend chart (items/daily), and a sortable items table (items/summary).
- Optional donut chart for UPI/Card/Cash share when data exists.
- Data table: columns order ID, KOT code, order type, payment type, location, amount, payment status chip, ERP/KDS status, items summary, created time (IST).
- Row opens drawer with detailed items; defensive parsing for item_name vs name on line items.
- Loading skeletons, empty states, error toasts; responsive layout; accessible focus in drawer.

Stack: [React + Vite + TanStack Query + Tailwind] or [Next.js App Router] — pick one and justify. No backend changes required.
```

---

## 9. Quick `curl` checks

```bash
# KPIs for today
curl -s -H "X-Store-Id: 1" "http://localhost:8000/analytics/summary?period=today" | jq

# Top 10 items today
curl -s -H "X-Store-Id: 1" "http://localhost:8000/analytics/items/top?period=today&limit=10" | jq

# Daily item counts for last week (all items)
curl -s -H "X-Store-Id: 1" "http://localhost:8000/analytics/items/daily?period=last_week" | jq

# Daily counts for one item (SKU drill-down)
curl -s -H "X-Store-Id: 1" "http://localhost:8000/analytics/items/daily?period=last_week&sku=10550601" | jq

# Full item summary for all time
curl -s -H "X-Store-Id: 1" "http://localhost:8000/analytics/items/summary?period=all_time" | jq

# Orders for all time, first page
curl -s -H "X-Store-Id: 1" "http://localhost:8000/orders?period=all_time&page=0&size=20" | jq

# One order
curl -s -H "X-Store-Id: 1" "http://localhost:8000/orders/KTR-1609D08171" | jq
```

---

## 10. Changelog reference

If `/analytics/summary` ever gains fields, treat this doc as stale until updated — verify against OpenAPI at `GET /docs` on the running server.

---

## 11. What you can learn about your store (Business Insights)

Using the Admin Dashboard, store owners and managers can extract deep operational and financial insights:

1. **Overall Performance & Growth**
   - **Total Revenue & Volume:** Quickly see how much money the store made and how many orders were processed today, yesterday, or historically.
   - **Sales Velocity:** Understand peak hours and off-peak hours (through the activity curves) to better schedule staff.

2. **Customer Behavior & Preferences**
   - **Dining Preferences:** See the split between Dine-in and Takeaway to understand if your store acts more as a fast-casual spot or a delivery/pickup hub.
   - **Payment Preferences:** Track how customers prefer to pay (UPI, Card, Cash). This helps in negotiating better rates with payment processors or managing cash-in-drawer limits.

3. **Product Performance (Item Analysis)**
   - **Bestsellers:** Identify the top-moving items to ensure sufficient stock and prep.
   - **Revenue Drivers:** Some items sell fewer quantities but drive higher revenue. The item summary reveals exactly which products are most profitable.
   - **Daily Trends:** Track if a specific item (e.g., Cold Coffee) spikes on certain days (like weekends) to optimize inventory and reduce wastage.

4. **Operational Health**
   - **Live Transactions:** Monitor the order grid to ensure orders are transitioning smoothly from PENDING to COMPLETED.
   - **Error Tracking:** The Logs tab helps technical staff or managers quickly identify if a payment terminal or KDS sync is failing in real-time.
