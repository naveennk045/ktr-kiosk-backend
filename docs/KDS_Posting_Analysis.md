# KDS (Kitchen Display System) Posting - Complete Analysis

## Overview

The KDS posting system integrates your restaurant's orders with **Rista KDS** (a third-party kitchen management system). When a customer pays for an order, your system sends order details to Rista so the kitchen can see what to prepare.

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPLETE KDS FLOW                             │
└─────────────────────────────────────────────────────────────────┘

1. CREATE ORDER
   ↓
   POST /orders
   ├─ Validate items against Rista Catalog (cached in Redis)
   ├─ Recalculate totals on backend (security: prevent tampering)
   ├─ Generate order_id (UUID: "ord-xxx...")
   ├─ Generate KOT code (Daily counter: "ktr-1", "ktr-2", ...)
   └─ Return order_id + KOT to client
       • Order Status: PENDING (no payment yet)
       • KDS Status: NOT_POSTED

2. PAYMENT INITIATION
   ↓
   POST /payments/qr/init OR POST /payments/edc/init
   ├─ Create PhonePe QR or push to EDC terminal
   ├─ Store qr_string / provider_txn_id in Order
   └─ Return QR code to customer
       • Order Status: PENDING
       • KDS Status: NOT_POSTED

3. CUSTOMER PAYS
   ↓
   ├─ Via UPI (scans QR) → PhonePe → Webhook
   └─ Via Card (EDC) → PhonePe → Webhook OR Status Check

4. WEBHOOK RECEIVED (FAST)
   ↓
   POST /payments/webhook/phonepe
   ├─ Verify X-VERIFY signature (CRITICAL: prevents tampering)
   ├─ Extract merchant_order_id, code
   ├─ Immediately return 200 OK (DON'T MAKE SLOW CALLS HERE)
   ├─ Add background task: process_webhook_in_background()
   └─ Return to client instantly
       • Status Endpoint returns: PENDING (until background completes)

5. BACKGROUND TASK (SLOW)
   ↓
   process_webhook_in_background()
   ├─ Load order from DB
   ├─ Update: payment_status = COMPLETED
   ├─ ATOMIC LOCK: Try to acquire KDS posting lock
   │  └─ UPDATE Order SET kds_status = PENDING
   │     WHERE id = ? AND kds_status = NOT_POSTED
   │     RETURNING kds_status
   ├─ If lock acquired (row returned):
   │  ├─ Fetch Rista catalog (cached)
   │  ├─ Build KDS payload with taxes
   │  ├─ POST to Rista with orderTransactionId = order_id (idempotency)
   │  ├─ On success:
   │  │  ├─ Extract invoiceNumber from response
   │  │  └─ Update: kds_status = POSTED, kds_invoice_id = invoiceNumber
   │  ├─ On 409 Conflict (order already exists):
   │  │  ├─ Query Rista with orderTransactionId
   │  │  ├─ If found: Update with existing invoiceNumber
   │  │  └─ Mark as POSTED
   │  └─ On failure: Mark as FAILED
   └─ If lock NOT acquired:
      └─ Skip (another process owns the KDS post)

6. ALTERNATIVE: STATUS CHECK
   ↓
   GET /payments/qr/status/{order_id} OR GET /payments/edc/status/{order_id}
   ├─ Load order from DB
   ├─ If payment_status already COMPLETED:
   │  ├─ Check if KDS still NOT_POSTED
   │  ├─ Try atomic lock (same as webhook)
   │  ├─ If lock acquired: Post to KDS
   │  └─ Return current status
   └─ If payment_status PENDING:
      ├─ Query PhonePe status endpoint
      ├─ Update order if changed
      ├─ If now COMPLETED: Acquire KDS lock and post
      └─ Return updated status

7. KDS RESPONSE STATES

   Order Complete ✅
   ├─ payment_status = COMPLETED
   ├─ kds_status = POSTED
   └─ kds_invoice_id = "123456" (Rista invoice number)

   Order Failed ❌
   ├─ payment_status = FAILED / kds_status = FAILED
   └─ kds_last_error = "Error message"

   Order Pending ⏳
   ├─ payment_status = PENDING
   └─ kds_status = NOT_POSTED / PENDING
```

---

## Database Schema (Order Model)

```sql
-- Key fields for KDS integration:

-- Payment Fields
payment_status      ENUM(PENDING, COMPLETED, FAILED, REFUNDED)
payment_method      ENUM(QR, EDC, MANUAL)
provider_txn_id     VARCHAR           -- PhonePe transaction ID
provider_code       VARCHAR           -- "SUCCESS", "PAYMENT_SUCCESS", etc.
provider_resp       JSONB             -- Raw PhonePe response

-- KOT (Kitchen Order Ticket)
kot_date            DATE              -- Today's date
kot_number          INT               -- Daily counter (1, 2, 3, ...)
kot_code            VARCHAR           -- "ktr-1", "ktr-2" (for kitchen display)

-- KDS Integration (NEW)
kds_status          ENUM(NOT_POSTED, PENDING, POSTED, FAILED)
kds_invoice_id      VARCHAR           -- Rista invoice number (from response)
kds_last_attempt_at DATETIME          -- When we last tried to post
kds_last_error      VARCHAR           -- Error message if posting failed

-- Unique Constraints (CRITICAL)
UNIQUE(order_id)                      -- Prevents duplicate order creation
UNIQUE(kot_date, kot_number)          -- One KOT per day per number
```

---

## KDS Posting Function: `post_order_to_kds()`

### Location
`app/core/rista_utils.py::post_order_to_kds()`

### Purpose
Posts a payment-completed order to Rista KDS with full tax breakdown.

### Key Features

#### 1. **Idempotency via `orderTransactionId`**
```python
# order.order_id is the idempotency key
# PhonePe can't process same order_id twice
"sourceInfo": {
    "orderTransactionId": order.order_id,  # ← Idempotency key
    "invoiceNumber": order.kot_code,       # ← Display KOT (ktr-1)
}
```
**Why?** If the KDS post fails and retries, Rista checks `orderTransactionId` and says:
- ✅ Already exists → Return 409 Conflict
- Your code then queries the existing order and marks as POSTED
- **Zero duplicate orders in kitchen!**

#### 2. **Atomic Locking (Race Condition Prevention)**
```python
# In both webhook handler and status endpoint:
result = await db.execute(
    update(Order)
    .where(
        Order.id == order.id,
        Order.kds_status == KdsStatus.NOT_POSTED,  # ← Only if not yet posted
    )
    .values(kds_status=KdsStatus.PENDING)  # ← Mark as "in progress"
    .returning(Order.kds_status)
)
row = result.first()  # ← If None, someone else changed it in parallel

if row:
    # THIS PROCESS OWNS THE KDS POST
    success, invoice = await post_order_to_kds(order, http_client, redis_client)
else:
    # ANOTHER PROCESS ALREADY OWNS IT - SKIP
    pass
```

**Race Scenario (Without Atomic Lock):**
```
Time  │  Webhook Handler           │  Status Check Endpoint
──────┼────────────────────────────┼──────────────────────
T1    │  Loads order (kds_status = NOT_POSTED)
T2    │                            │  Loads same order (kds_status = NOT_POSTED)
T3    │  Posts to KDS...           │
T4    │  Gets 200 OK → POSTED      │  Posts to KDS...
T5    │  Marks kds_status = POSTED │  Gets 200 OK → POSTED
T6    │  Commits                   │  Both now marked POSTED
      │                            │  (Order appears twice in kitchen!)
```

**With Atomic Lock:**
```
Time  │  Webhook Handler           │  Status Check Endpoint
──────┼────────────────────────────┼──────────────────────
T1    │  ATOMIC: Try to lock
T2    │  ✅ Lock acquired (kds_status = PENDING)
T3    │                            │  ATOMIC: Try to lock
T4    │                            │  ❌ Lock NOT acquired (kds_status already PENDING)
T5    │  Posts to KDS              │  Skips KDS post
T6    │  Marks POSTED              │  Returns current status
T7    │  Commits                   │  No duplicate! ✅
```

#### 3. **Tax Calculation (Complex)**
```python
# For each item, calculate tax based on:
# 1. Is price INCLUSIVE or EXCLUSIVE of tax?
# 2. What are the applicable tax rates (CGST, SGST, VAT)?

def calculate_tax_amounts(sale_amount, tax_percentage, price_includes_tax):
    if price_includes_tax:
        # Reverse calculation
        # Price = 100, Tax = 5%, Amount = 100 / 1.05 = ~95.24
        tax_amount = (sale_amount * tax_percentage) / (100 + tax_percentage)
    else:
        # Forward calculation
        # Price = 100, Tax = 5%, Amount = 100 * 0.05 = 5
        tax_amount = (sale_amount * tax_percentage) / 100
    return tax_amount
```

**Example:**
```
Item: Dosa
Price in Catalog: ₹100 (INCLUSIVE of 5% CGST)

Step 1: Get from Catalog
├─ isPriceIncludesTax = true
├─ taxTypeIds = [cgst_5%, sgst_5%]
└─ price = 100

Step 2: Calculate Taxes
├─ Total Tax Included = (100 * 5) / (100 + 5) ≈ ₹4.76
└─ Total Tax Excluded = ₹0

Step 3: Build KDS Item
{
    "shortName": "Dosa",
    "skuCode": "123",
    "quantity": 2,
    "unitPrice": 100,
    "itemAmount": 200,
    "itemTotalAmount": 200,
    "taxAmountIncluded": 9.52,  (2 × 4.76)
    "taxes": [
        {
            "name": "CGST",
            "percentage": 5,
            "saleAmount": 200,
            "amountIncluded": 4.76,
            "amountExcluded": 0,
        },
        {
            "name": "SGST",
            "percentage": 5,
            "saleAmount": 200,
            "amountIncluded": 4.76,
            "amountExcluded": 0,
        }
    ]
}
```

### Complete Payload Structure

```json
POST https://rista-kds-api/sale
{
    "branchCode": "BRN001",
    "channel": "Palas Kiosk",
    "status": "Closed",              // Payment already done
    "sourceInfo": {
        "source": "Palas Kiosk",
        "orderTransactionId": "ord-abc123",  // ← IDEMPOTENCY KEY
        "invoiceNumber": "ktr-5",            // ← Display KOT
        "invoiceDate": "2025-11-16T18:30:00Z"
    },
    "items": [
        {
            "shortName": "Idli",
            "skuCode": "SKU001",
            "quantity": 2,
            "unitPrice": 30.0,
            "itemAmount": 60.0,
            "itemTotalAmount": 60.0,
            "itemNature": "Service",
            "taxAmountIncluded": 2.86,
            "taxes": [
                {
                    "name": "CGST",
                    "percentage": 5,
                    "saleAmount": 60.0,
                    "amountIncluded": 1.43,
                    "amountExcluded": 0.0,
                    "amount": 1.43
                }
            ]
        }
    ],
    "itemTotalAmount": 60.0,
    "taxAmountIncluded": 2.86,
    "billAmount": 62.86,
    "billRoundedAmount": 62.86,
    "roundOffAmount": 0.0,
    "tipAmount": 0.0,
    "totalAmount": 62.86,
    "payments": [
        {
            "mode": "QR",
            "amount": 62.86,
            "reference": "order-abc123",
            "postedDate": "2025-11-16T18:30:00Z"
        }
    ],
    "taxes": [
        {
            "name": "CGST",
            "percentage": 5,
            "saleAmount": 60.0,
            "itemTaxIncluded": 1.43,
            "itemTaxExcluded": 0.0,
            "amount": 1.43
        }
    ]
}
```

### Rista API Response (Success)

```json
{
    "success": true,
    "code": "SUCCESS",
    "message": "Sale created successfully",
    "data": {
        "invoiceNumber": "123456",    // ← STORE THIS in kds_invoice_id
        "saleDate": "2025-11-16",
        "totalAmount": 62.86,
        "status": "Closed"
    }
}
```

### Error Handling

#### 409 Conflict (Order Already Exists)
```python
if e.response.status_code == 409:
    # Rista says: "This orderTransactionId already posted"
    exists, existing_invoice = await check_existing_sale(order.order_id, http_client)
    if exists:
        # Query confirms it exists with invoice_id
        order.kds_invoice_id = existing_invoice
        order.kds_status = KdsStatus.POSTED
        return True, existing_invoice
    else:
        # 409 but query says it doesn't exist?
        # Likely race condition between systems
        order.kds_status = KdsStatus.FAILED
        return False, None
```

#### Other Errors
```
- 400 Bad Request → KDS says payload is wrong → Likely SKU mismatch
- 401 Unauthorized → JWT token invalid
- 500 Server Error → Rista KDS is down → Should retry
- Network Error (timeout) → Connection issue → Should retry
```

---

## JWT Token Generation for Rista

### Location
`app/core/rista_utils.py::generate_jwt_token()`

```python
def generate_jwt_token(request_id: str | None = None) -> str:
    """
    Generates HS256 JWT for Rista API authentication.
    
    For idempotency, request_id should be unique per operation.
    """
    token_creation_time = int(time.time())
    payload = {
        "iss": settings.PI_KEY,        # Issuer (merchant ID)
        "iat": token_creation_time,    # Issued at
    }
    
    if request_id:
        payload["jti"] = f"{request_id}_{token_creation_time}"  # Unique ID
    
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token
```

### Usage for KDS Posting
```python
# Generate with unique request ID
request_id = f"kds_{order.order_id}_{int(time.time() * 1000)}"
token = await run_in_threadpool(generate_jwt_token, request_id)

headers = {
    "x-api-key": settings.PI_KEY,
    "x-api-token": token,
    "content-type": "application/json",
}
```

---

## Catalog Caching

### Why Cache?
- Rista catalog is fetched for every KDS post
- Catalog doesn't change frequently
- Redis caching prevents repeated API calls

### Location
`app/core/rista_utils.py::get_catalog_data()`

```python
async def get_catalog_data(channel, redis_client, http_client):
    cache_key = f"{channel}_catalog_data"
    
    # 1. Check Redis first
    if cached_data := await redis_client.get(cache_key):
        return json.loads(cached_data)
    
    # 2. If not cached, fetch from Rista
    token = generate_jwt_token()  # No jti needed for GET
    response = await http_client.get(url, headers=headers, params=params)
    catalog = response.json()
    
    # 3. Cache for 1 hour
    await redis_client.set(cache_key, json.dumps(catalog), ex=3600)
    return catalog
```

### Cache Keys
```
"Palas Kiosk_catalog_data"      # For Palas Kiosk channel
"QSR Hub_catalog_data"          # For QSR Hub channel
```

### Cache Invalidation
Currently: **Manual TTL (1 hour)**
- After 1 hour, cache expires
- Next request fetches fresh data

**Improvement:** Add cache invalidation endpoint
```python
@router.delete("/catalog/cache")
async def clear_catalog_cache(channel: str, redis_client = Depends(get_redis_client)):
    await redis_client.delete(f"{channel}_catalog_data")
    return {"message": "Cache cleared"}
```

---

## Two Paths to KDS Posting

### Path 1: Webhook (Async Background)
```
PhonePe → Webhook → Verify Signature → Background Task → KDS Post
├─ FAST: Callback returns 200 OK instantly
├─ SLOW: Background task handles KDS post
└─ Best for: Server-initiated payments
```

**Code:**
```python
# app/routers/payment/callback.py
@router.post("/phonepe")
async def handle_phonepe_callback(request, background_tasks):
    # 1. Verify signature (fast)
    # 2. Add slow task to background
    background_tasks.add_task(
        process_webhook_in_background,
        merchant_order_id=order_id,
        code=code,
        payload=payload,
        ...
    )
    # 3. Return 200 OK immediately
    return {"status": "ok"}
```

### Path 2: Status Check (Sync)
```
Client → /status endpoint → Query PhonePe → Update DB → KDS Post
├─ Returns status immediately
├─ Polls PhonePe if status is PENDING
└─ Best for: Client-initiated status checks
```

**Code:**
```python
# app/routers/payment/dynamic_qr.py
@router.get("/status/{order_id}")
async def get_payment_status(order_id, db, http_client, redis_client):
    # 1. Load order
    # 2. If status is PENDING, query PhonePe
    # 3. Update DB if status changed
    # 4. If payment completed, try KDS lock and post
    # 5. Return current status
```

---

## Race Condition Scenarios & Solutions

### Scenario 1: Webhook vs Status Check (SOLVED)
```
Webhook arrives:
  ├─ Tries to acquire KDS lock → SUCCESS
  └─ Posts to KDS

Meanwhile, client also calls:
  GET /payments/qr/status/{order_id}
  ├─ Tries to acquire KDS lock → FAILS (webhook owns it)
  └─ Skips KDS post
  
Result: ✅ Only one KDS post
```

### Scenario 2: Webhook Retried by PhonePe (SOLVED)
```
Same webhook arrives twice (PhonePe retry):
  ├─ First callback: Posts to KDS successfully → kds_status = POSTED
  ├─ Second callback: Tries to acquire lock → FAILS (already POSTED)
  └─ Skips KDS post
  
Result: ✅ Only one KDS post (idempotency works)
```

### Scenario 3: KDS Post Fails (NEEDS IMPROVEMENT)
```
KDS post fails (e.g., network timeout):
  ├─ order.kds_status = FAILED
  ├─ order.kds_last_error = "Timeout"
  ├─ order.kds_last_attempt_at = now
  
No automatic retry currently!
Suggested fix:
  ├─ Add kds_retry_count field
  ├─ If FAILED and retry_count < 3:
  │  └─ Schedule background task to retry after 30 seconds
  └─ Mark as FAILED only after 3 attempts
```

---

## Status Transitions (State Machine)

```
Order Created
     ↓
payment_status = PENDING, kds_status = NOT_POSTED
     ↓
(Customer pays or timeout)
     ↓
IF Payment SUCCESS:
  payment_status = COMPLETED
        ↓
  Try to acquire KDS lock
        ↓
  IF lock acquired:
     kds_status = PENDING → Posting...
           ↓
     IF KDS post SUCCESS:
        kds_status = POSTED ✅
           ↓
        Order complete (kitchen sees it)
           
     IF KDS post FAILED:
        kds_status = FAILED ❌
           ↓
        Needs manual retry or automatic retry mechanism

  IF lock NOT acquired:
     Skip (another process owns KDS post)

ELSE Payment FAILED:
  payment_status = FAILED
        ↓
  kds_status remains NOT_POSTED
        ↓
  Order rejected (no kitchen order)
```

---

## Testing Checklist

### Unit Tests
- [ ] `generate_jwt_token()` creates valid tokens
- [ ] `calculate_tax_amounts()` correctly handles inclusive/exclusive tax
- [ ] `build_item_with_taxes()` builds correct payload
- [ ] `summarize_sale_taxes()` aggregates correctly

### Integration Tests
- [ ] Create order → generates KOT
- [ ] Pay order → webhook triggers KDS post
- [ ] Get status → acquires lock if needed
- [ ] 409 conflict handled correctly
- [ ] Duplicate webhook doesn't create duplicate KDS order

### Load Tests
- [ ] 100 concurrent orders created (KOT race-free?)
- [ ] 50 webhooks arriving simultaneously (only one KDS post?)
- [ ] Catalog cache working under load

### Error Scenarios
- [ ] Rista API timeout → kds_status = FAILED
- [ ] Invalid SKU → kds_last_error populated
- [ ] Network error → handled gracefully
- [ ] JWT generation failure → order.kds_status = FAILED

---

## Configuration (.env)

```env
# Rista KDS
RISTA_BASE_URL=https://rista-api.example.com
PI_KEY=merchant_id_here
SECRET_KEY=jwt_secret_key_here
BRANCH_CODE=BRN001

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# PhonePe (for callbacks)
PHONEPE_CALLBACK_URL=https://your-api.com/payments/webhook/phonepe
```

---

## Summary

| Component | Purpose | Status |
|-----------|---------|--------|
| `post_order_to_kds()` | Main KDS posting logic | ✅ Solid |
| Atomic locking | Prevent duplicate posts | ✅ Implemented |
| Idempotency | Handle retries safely | ✅ Via orderTransactionId |
| Tax calculation | Complex tax logic | ✅ Correct |
| Catalog caching | Performance optimization | ✅ 1hr TTL |
| Webhook handling | Async background task | ✅ 200 OK fast return |
| Error handling | 409 Conflict, timeouts | ⚠️ Could be better |
| Retry logic | Failed KDS posts | ❌ Missing (IMPROVEMENT NEEDED) |
| JWT generation | Rista authentication | ✅ With jti for idempotency |

---

## Recommended Improvements

1. **Add KDS Retry Logic** (Priority: HIGH)
   ```python
   kds_retry_count: int = 0
   kds_max_retries: int = 3
   kds_next_retry_at: datetime = None
   ```

2. **Add Monitoring** (Priority: MEDIUM)
   - Log all KDS posts with timestamps
   - Alert if kds_status = FAILED
   - Dashboard showing KDS sync health

3. **Add Cache Invalidation Endpoint** (Priority: LOW)
   - Manual trigger to clear catalog cache

4. **Consolidate Catalog Logic** (Priority: MEDIUM)
   - Currently duplicated in `router/catalog.py` and `rista_utils.py`
   - Use only `rista_utils.get_catalog_data()`