# Breaking Change: `store_id` → `terminal_id` in Payment Requests

**Date:** 2026-03-16  
**Affects:** All payment initiation API calls (QR, EDC/Card, Cash)

---

## What Changed

The field `store_id` has been **renamed to `terminal_id`** in all payment request payloads.

The backend will now **reject** any request that sends `store_id` — it will return a `422 Unprocessable Entity`.

---

## Changes Required in Frontend

### 1. EDC / Card Payment — `POST /payment/edc/init`

`terminal_id` is **required**.

```diff
- { "order_id": "ORD-001", "amount_paise": 5000, "store_id": "YOUR_CLIENT_ID" }
+ { "order_id": "ORD-001", "amount_paise": 5000, "terminal_id": "YOUR_CLIENT_ID" }
```

> The value stays the same — it's the Pine Labs terminal's **ClientID**. Only the key name changes.

> ⚠️ If no EDC config exists for the given `terminal_id`, the backend will return **404** with the message: `"No EDC config found for terminal_id '...'. Please provide a valid terminal ID."`

---

### 2. QR Payment — `POST /payment/qr/init`

`terminal_id` is **optional**.

```diff
- { "order_id": "ORD-001", "amount_paise": 5000, "store_id": "STORE_X" }
+ { "order_id": "ORD-001", "amount_paise": 5000, "terminal_id": "STORE_X" }
```

> If omitted, it's fine — `terminal_id` is stored on the order for traceability only. QR payments use the server-side PhonePe config regardless.

---

### 3. Cash Payment — `POST /payment/cash/init`

`terminal_id` is **optional**.

```diff
- { "order_id": "ORD-001", "amount_paise": 5000, "store_id": "STORE_X", "pin": "1234" }
+ { "order_id": "ORD-001", "amount_paise": 5000, "terminal_id": "STORE_X", "pin": "1234" }
```

---

## Summary Table

| Endpoint | Field | Required? |
|---|---|---|
| `POST /payment/edc/init` | `terminal_id` | ✅ Required |
| `POST /payment/qr/init` | `terminal_id` | Optional |
| `POST /payment/cash/init` | `terminal_id` | Optional |

---

## No Changes Needed

The following endpoints are **not affected**:
- `GET /payment/edc/status/{order_id}`
- `GET /payment/qr/status/{order_id}`
- `GET /catalog/{channel}`
- All order creation endpoints
