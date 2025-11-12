  # KTR Kiosk API Documentation

## Overview

The Kiosk Payment System API provides endpoints for managing product catalogs, creating orders, and processing payments through QR codes and EDC (Electronic Data Capture) devices. This API is designed for POS kiosk applications.

**Base URL:** `http://127.0.0.1:8000/`

**Channel:** `Palas Kiosk`

---

## Authentication

- **No Auth**
---

## Endpoints

### 1. Get Catalog

Retrieve all available products, categories, and pricing information for the kiosk.

**Endpoint:** `GET /catalog/?channel=Palas Kiosk`

**Method:** GET

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| channel | string | Yes | The channel identifier (e.g., "Palas Kiosk") |

**Request Example:**
```bash
curl -X GET "http://127.0.0.1:8000/catalog/?channel=Palas Kiosk" \
```

**Response Format (200 OK):**
```json
{
  "categories": [
    {
      "categoryId": "string",
      "name": "string",
      "subCategories": []
    }
  ],
  "schedules": [],
  "itemTags": [
    {
      "itemTagId": "string",
      "name": "string"
    }
  ],
  "charges": [
    {
      "chargeId": "string",
      "name": "string",
      "applyAt": "string",
      "applicableModes": ["string"],
      "chargeType": "string",
      "chargeRate": number,
      "taxTypeIds": ["string"],
      "isIncludesTax": boolean
    }
  ],
  "items": [
    {
      "itemId": "string",
      "type": "string",
      "skuCode": "string",
      "price": number,
      "itemName": "string",
      "status": "string",
      "measuringUnit": "string",
      "chargeIds": ["string"],
      "taxTypeIds": ["string"],
      "categoryId": "string",
      "itemTagIds": ["string"],
      "imageURL": "string",
      "scheduleIds": ["string"],
      "itemNature": "string",
      "isPriceIncludesTax": boolean,
      "denyDiscount": boolean
    }
  ],
  "optionSets": [],
  "discounts": [],
  "memberships": [],
  "taxTypes": [
    {
      "taxTypeId": "string",
      "percentage": number,
      "name": "string"
    }
  ]
}
```

**Response Fields:**

- **categories**: Array of product categories available in the catalog
- **itemTags**: Available tags for filtering/categorizing items (Vegetarian, Spicy, etc.)
- **charges**: Additional charges applicable to orders (e.g., platform charge)
- **items**: List of all available products with pricing and tax information
- **taxTypes**: Tax configurations (CGST, SGST, VAT, etc.)

**Example Response (Partial):**
```json
{
  "categories": [
    {
      "categoryId": "68e778dd0c42e107fdf5cf3f",
      "name": "BEVERAGE",
      "subCategories": []
    },
    {
      "categoryId": "6868ca5dc29c8ed4d3c98dd3",
      "name": "Davanagere Dose",
      "subCategories": []
    }
  ],
  "items": [
    {
      "itemId": "6868ca5d4fda6eabd33ccba2",
      "type": "Simple",
      "skuCode": "1",
      "price": 110,
      "itemName": "Davanagere Benne Sada Dose",
      "status": "Active",
      "measuringUnit": "ea",
      "chargeIds": [],
      "taxTypeIds": ["6868c05ede387c9d22a94396", "6868c05ede387c9d22a94397"],
      "categoryId": "6868ca5dc29c8ed4d3c98dd3",
      "itemTagIds": ["6868c0ab6065bace3cd952b7"],
      "imageURL": "https://static.apps.ristaapps.com/...",
      "scheduleIds": [],
      "itemNature": "Service",
      "isPriceIncludesTax": false,
      "denyDiscount": false
    }
  ],
  "taxTypes": [
    {
      "taxTypeId": "6868c05ede387c9d22a94396",
      "percentage": 2.5,
      "name": "CGST"
    },
    {
      "taxTypeId": "6868c05ede387c9d22a94397",
      "percentage": 2.5,
      "name": "SGST"
    }
  ]
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Missing or invalid channel parameter |
| 500 | Internal server error |

---

### 2. Create Order

Create a new order with selected items and pricing information.

**Endpoint:** `POST /orders/`

**Method:** POST

**Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "channel": "string",
  "items": [
    {
      "item_skuid": "string",
      "quantity": number
    }
  ],
  "total_amount_include_tax": number,
  "total_amount_exclude_tax": number
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| channel | string | Yes | Channel identifier (e.g., "Palas Kiosk") |
| items | array | Yes | Array of items in the order |
| items[].item_skuid | string | Yes | SKU code of the item (e.g., "7", "27") |
| items[].quantity | number | Yes | Quantity of the item |
| total_amount_include_tax | number | Yes | Total amount including taxes (in INR) |
| total_amount_exclude_tax | number | Yes | Total amount excluding taxes (in INR) |

**Request Example:**
```bash
curl -X POST "http://127.0.0.1:8000/orders/" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "Palas Kiosk",
    "items": [
      {
        "item_skuid": "7",
        "quantity": 2
      },
      {
        "item_skuid": "27",
        "quantity": 1
      }
    ],
    "total_amount_include_tax": 420.0,
    "total_amount_exclude_tax": 400.0
  }'
```

**Response Format (201 Created):**
```json
{
  "order_id": "string",
  "total_amount_include_tax": number,
  "total_amount_exclude_tax": number
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| order_id | string | Unique identifier for the created order (e.g., "ktr-35") |
| total_amount_include_tax | number | Total amount including taxes (in INR) |
| total_amount_exclude_tax | number | Total amount excluding taxes (in INR) |

**Example Response:**
```json
{
  "order_id": "ktr-35",
  "total_amount_include_tax": 420.0,
  "total_amount_exclude_tax": 400.0
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Invalid request body or missing required fields |
| 409 | Conflict - Order already exists or SKU not found |
| 500 | Internal server error |

---

### 3. QR Payment Initialization

Initialize a QR code payment session for an order.

**Endpoint:** `POST /payments/qr/init`

**Method:** POST

**Headers:**
```
Content-Type: application/json
Authorization: Bearer <token>
```

**Request Body:**
```json
{
  "order_id": "string",
  "amount_paise": "string"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| order_id | string | Yes | Order ID returned from create-order endpoint |
| amount_paise | string | Yes | Payment amount in paise (1 INR = 100 paise) |

**Request Example:**
```bash
curl -X POST "http://127.0.0.1:8000/payments/qr/init" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ktr-24",
    "amount_paise": "42000"
  }'
```

**Response Format (200 OK):**
```json
{
  "order_id": "string",
  "amount_paise": "string",
  "qr_code": "string",
  "status": "INITIATED",
  "timestamp": "string"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| order_id | string | The order ID for this payment |
| amount_paise | string | Amount in paise |
| qr_code | string | QR code data/image URL for scanning |
| status | string | Payment status (INITIATED, PENDING, COMPLETED, FAILED) |
| timestamp | string | ISO 8601 timestamp of initialization |

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Invalid order_id or amount_paise |
| 404 | Order not found |
| 500 | Internal server error |

---

### 4. QR Payment Status Check

Check the status of a QR payment.

**Endpoint:** `GET /payments/qr/status/{order_id}`

**Method:** GET

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_id | string | Yes | Order ID to check payment status |

**Request Example:**
```bash
curl -X GET "http://127.0.0.1:8000/payments/qr/status/ktr-14" \
```

**Response Format (200 OK):**
```json
{
  "order_id": "string",
  "amount_paise": "string",
  "status": "string",
  "payment_method": "QR",
  "transaction_id": "string",
  "payment_timestamp": "string",
  "created_at": "string"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| order_id | string | The order ID |
| amount_paise | string | Amount in paise |
| status | string | Current payment status (PENDING, COMPLETED, FAILED, REFUNDED) |
| payment_method | string | Always "QR" for this endpoint |
| transaction_id | string | Unique transaction identifier (if payment successful) |
| payment_timestamp | string | ISO 8601 timestamp when payment was completed |
| created_at | string | ISO 8601 timestamp when payment was initiated |

**Example Response:**
```json
{
  "order_id": "ktr-14",
  "amount_paise": "42000",
  "status": "COMPLETED",
  "payment_method": "QR",
  "transaction_id": "TXN-2024-001",
  "payment_timestamp": "2024-11-11T12:30:45Z",
  "created_at": "2024-11-11T12:25:00Z"
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 404 | Order not found or payment not initiated |
| 500 | Internal server error |

---

### 5. EDC Payment Initialization

Initialize an EDC (card/terminal) payment session for an order.

**Endpoint:** `POST /payments/edc/init`

**Method:** POST

**Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "order_id": "string",
  "amount_paise": "string"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| order_id | string | Yes | Order ID returned from create-order endpoint |
| amount_paise | string | Yes | Payment amount in paise |

**Request Example:**
```bash
curl -X POST "http://127.0.0.1:8000/payments/edc/init" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ktr-26",
    "amount_paise": "42000"
  }'
```

**Response Format (200 OK):**
```json
{
  "order_id": "string",
  "amount_paise": "string",
  "edc_reference": "string",
  "status": "INITIATED",
  "timestamp": "string",
  "device_id": "string"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| order_id | string | The order ID |
| amount_paise | string | Amount in paise |
| edc_reference | string | Reference ID for this EDC transaction |
| status | string | EDC transaction status (INITIATED, AWAITING_CARD, PROCESSING, COMPLETED, FAILED) |
| timestamp | string | ISO 8601 timestamp |
| device_id | string | Identifier of the EDC device |

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Invalid order_id or amount_paise |
| 401 | Unauthorized |
| 404 | Order not found |
| 503 | EDC device unavailable |
| 500 | Internal server error |

---

### 6. EDC Payment Status Check

Check the status of an EDC payment.

**Endpoint:** `GET /payments/edc/status/{order_id}`

**Method:** GET

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_id | string | Yes | Order ID to check payment status |

**Request Example:**
```bash
curl -X GET "http://127.0.0.1:8000/payments/edc/status/ktr-26" \
```

**Response Format (200 OK):**
```json
{
  "order_id": "string",
  "amount_paise": "string",
  "status": "string",
  "payment_method": "EDC",
  "transaction_id": "string",
  "edc_reference": "string",
  "card_last_four": "string",
  "payment_timestamp": "string",
  "created_at": "string"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| order_id | string | The order ID |
| amount_paise | string | Amount in paise |
| status | string | Current payment status (PENDING, COMPLETED, FAILED, CANCELLED) |
| payment_method | string | Always "EDC" for this endpoint |
| transaction_id | string | Unique transaction identifier |
| edc_reference | string | EDC device reference for this transaction |
| card_last_four | string | Last 4 digits of the card used |
| payment_timestamp | string | ISO 8601 timestamp when payment completed |
| created_at | string | ISO 8601 timestamp when payment initiated |

**Example Response:**
```json
{
  "order_id": "ktr-26",
  "amount_paise": "42000",
  "status": "COMPLETED",
  "payment_method": "EDC",
  "transaction_id": "TXN-2024-002",
  "edc_reference": "EDC-REF-12345",
  "card_last_four": "4242",
  "payment_timestamp": "2024-11-11T12:35:20Z",
  "created_at": "2024-11-11T12:30:00Z"
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 401 | Unauthorized |
| 404 | Order not found or payment not initiated |
| 500 | Internal server error |

---
## Backend
### 7. Payment Webhook (PhonePe Callback)

Receive payment status updates from PhonePe for QR payments.

**Endpoint:** `POST /payments/webhook/phonepe`

**Method:** POST

**Headers:**
```
Content-Type: application/json
X-VERIFY: <signature>###<index>
```

**Authentication:**

This endpoint uses signature verification for security:
- **Header:** `X-VERIFY`
- **Format:** `{signature}###{index}`
- **Example:** `1c5eacd02c973624244f3dcb10e9b20cb9c51f392939e8d83cc6246ae6bf1ae2###1`

**Request Body:**
```json
{
  "response": "base64_encoded_json_string"
}
```

**Decoded Response Format:**
```json
{
  "success": boolean,
  "code": "string",
  "message": "string",
  "data": {
    "merchantId": "string",
    "transactionId": "string",
    "providerReferenceId": "string",
    "amount": number,
    "merchantOrderId": "string",
    "paymentTimestamp": number,
    "paymentState": "string",
    "payResponseCode": "string",
    "transactionContext": {
      "qrCodeId": "string",
      "posDeviceId": "string",
      "storeId": "string",
      "terminalId": "string"
    }
  }
}
```

**Request Example:**
```bash
curl -X POST "http://localhost:8000/payments/webhook/phonepe" \
  -H "Content-Type: application/json" \
  -H "X-VERIFY: 1c5eacd02c973624244f3dcb10e9b20cb9c51f392939e8d83cc6246ae6bf1ae2###1" \
  -d '{
    "response": "eyJzdWNjZXNzIjp0cnVlLCJjb2RlIjoiUEFZTUVOVF9TVUNDRVNTIiwibWVzc2FnZSI6IllvdXIgcGF5bWVudCBpcyBzdWNjZXNzZnVsLiIsImRhdGEiOnsibWVyY2hhbnRJZCI6IkhJTUFMQVlBTlNBVk9VUlVBVCIsInRyYW5zYWN0aW9uSWQiOiJlNDgwNGY3YS1kOTk5LTQwMjctOGYwMy1lYjA2NDc5YzEwMTciLCJwcm92aWRlclJlZmVyZW5jZUlkIjoiVDI1MTEwNzE0NDEyMTU3OTE2NTk0MDgiLCJhbW91bnQiOjM3OCwibWVyY2hhbnRPcmRlcklkIjoiZTQ4MDRmN2EtZDk5OS00MDI3LThmMDMtZWIwNjQ3OWMxMDE3IiwicGF5bWVudFRpbWVzdGFtcCI6MTY5Njk1OTQ3MDkzNywicGF5bWVudFN0YXRlIjoiQ09NUExFVEVEIiwicGF5UmVzcG9uc2VDb2RlIjoiU1VDQ0VTUyIsInRyYW5zYWN0aW9uQ29udGV4dCI6eyJxckNvZGVJZCI6bnVsbCwicG9zRGV2aWNlSWQiOm51bGwsInN0b3JlSWQiOm51bGwsInRlcm1pbmFsSWQiOm51bGx9fX0="
  }'
```

**Decoded Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| success | boolean | Whether payment was successful |
| code | string | Response code (e.g., PAYMENT_SUCCESS, PAYMENT_FAILED) |
| message | string | Human-readable message |
| data.merchantId | string | Merchant identifier |
| data.transactionId | string | Unique transaction ID |
| data.providerReferenceId | string | PhonePe reference ID |
| data.amount | number | Payment amount in paise |
| data.merchantOrderId | string | Your order ID |
| data.paymentTimestamp | number | Unix timestamp of payment |
| data.paymentState | string | Payment state (COMPLETED, FAILED, etc.) |
| data.payResponseCode | string | Payment response code (SUCCESS, FAILED) |

**Response Format (200 OK):**
```json
{
  "status": "SUCCESS",
  "message": "Webhook received and processed"
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Invalid signature or malformed response |
| 401 | Signature verification failed |
| 422 | Invalid base64 encoded response |
| 500 | Internal server error |

---

## Data Models

### Item Object

```json
{
  "itemId": "string",
  "type": "Simple|Combo|Bundle",
  "skuCode": "string",
  "price": number,
  "itemName": "string",
  "status": "Active|Inactive|Discontinued",
  "measuringUnit": "ea|kg|liters",
  "chargeIds": ["string"],
  "taxTypeIds": ["string"],
  "categoryId": "string",
  "itemTagIds": ["string"],
  "imageURL": "string",
  "scheduleIds": ["string"],
  "itemNature": "Service|Product",
  "isPriceIncludesTax": boolean,
  "denyDiscount": boolean
}
```

### Category Object

```json
{
  "categoryId": "string",
  "name": "string",
  "subCategories": ["string"]
}
```

### Tax Type Object

```json
{
  "taxTypeId": "string",
  "percentage": number,
  "name": "CGST|SGST|VAT|etc"
}
```

### Charge Object

```json
{
  "chargeId": "string",
  "name": "string",
  "applyAt": "Order|Item",
  "applicableModes": ["Delivery", "Pickup", "Others"],
  "chargeType": "Absolute|Percentage",
  "chargeRate": number,
  "taxTypeIds": ["string"],
  "isIncludesTax": boolean
}
```

---

## Common Response Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| SUCCESS | 200 | Request successful |
| CREATED | 201 | Resource created successfully |
| BAD_REQUEST | 400 | Invalid request parameters |
| NOT_FOUND | 404 | Resource not found |
| CONFLICT | 409 | Resource already exists or conflict |
| INTERNAL_ERROR | 500 | Server error |

---

## Payment Status Flow

### QR Payment Flow

```
1. Create Order → order_id
2. Initialize QR Payment → qr_code + INITIATED status
3. Customer scans QR → Payment Processing
4. Poll Status Check → Check for COMPLETED status
5. Webhook Callback → Final confirmation (optional)
```

### EDC Payment Flow

```
1. Create Order → order_id
2. Initialize EDC Payment → edc_reference + INITIATED status
3. Customer inserts/taps card → AWAITING_CARD → PROCESSING
4. Poll Status Check → Check for COMPLETED status
5. Response with card details
```

---

## Error Handling

All error responses follow this format:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": "string",
    "timestamp": "string"
  }
}
```

**Example Error Response:**

```json
{
  "error": {
    "code": "ORDER_NOT_FOUND",
    "message": "The specified order does not exist",
    "details": "Order ID: ktr-99 not found in database",
    "timestamp": "2024-11-11T12:45:30Z"
  }
}
```

---

## Implementation Notes for Frontend

### Best Practices

1. **Polling Strategy for Payment Status:**
   - Initial poll: Immediately after payment initialization
   - Subsequent polls: Every 2-3 seconds
   - Maximum polls: 30-60 depending on timeout requirement
   - Recommended timeout: 5-10 minutes

2. **Error Handling:**
   - Implement retry logic with exponential backoff for transient errors
   - Display user-friendly error messages for payment failures
   - Log transaction IDs for customer support

3. **Amount Conversion:**
   - Always work in paise (divide by 100 to get INR)
   - Ensure proper rounding in currency calculations
   - Example: ₹420 = 42000 paise

4. **Webhook Verification:**
   - Always verify X-VERIFY signature before processing
   - Decode base64 response before parsing JSON
   - Store webhook data for audit trail

5. **Security:**
   - Never expose authentication tokens in frontend code
   - Use backend proxy for all API calls
   - Implement CORS properly for kiosk applications
   - Validate all user inputs before sending to API

---

## Testing

### Sample Test Data

- **Test Order IDs:** ktr-24, ktr-26, ktr-35
- **Test Amount:** 42000 paise (₹420)
- **Test Items:** SKU codes 7 and 27

### Test Workflow

```bash
# 1. Get Catalog
curl -X GET "http://127.0.0.1:8000/catalog/?channel=Palas Kiosk"

# 2. Create Order
curl -X POST "http://127.0.0.1:8000/orders/" \
  -H "Content-Type: application/json" \
  -d '{"channel":"Palas Kiosk","items":[{"item_skuid":"7","quantity":2}],"total_amount_include_tax":420,"total_amount_exclude_tax":400}'

# 3. Initialize QR Payment
curl -X POST "http://127.0.0.1:8000/payments/qr/init" \
  -H "Content-Type: application/json" \
  -d '{"order_id":"ktr-35","amount_paise":"42000"}'

# 4. Check Payment Status
curl -X GET "http://127.0.0.1:8000/payments/qr/status/ktr-35"
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-11-11 | Initial API documentation |

---

## Support

For integration support or questions, contact the development team with:
- **Transaction ID** (if available)
- **Order ID**
- **Request/Response payload**
- **Timestamp of issue**
