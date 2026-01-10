# KTR Kiosk Backend API Documentation

## 1. Catalog API

### Get Catalog
Retrieves the full menu catalog for a specific channel, including categories, items, and taxes.

**Endpoint**: `GET /catalog/`
**Parameters**:
- `channel` (query param, required): The source channel, e.g., "Palas Kiosk".

**Response**:
```json
{
  "categories": [
    {
      "categoryId": "68e778dd0c42e107fdf5cf3f",
      "name": "BEVERAGE",
      "subCategories": []
    },
    ...
  ],
  "items": [
    {
      "itemId": "6868ca5d4fda6eabd33ccba2",
      "type": "Simple",
      "skuCode": "1",
      "price": 110,
      "itemName": "Davanagere Benne Sada Dose",
      "status": "Active",
      ...
    },
    ...
  ],
  "taxTypes": [
    {
      "taxTypeId": "6868c05ede387c9d22a94396",
      "percentage": 2.5,
      "name": "CGST"
    },
    ...
  ]
}
```

---

## 2. Order API

### Create Order
Creates a new order, calculates taxes, generates a KOT number, and returns the order ID.

**Endpoint**: `POST /orders/`

**Request Body**:
```json
{
  "channel": "Palas Kiosk",
  "order_type": "DINEIN",
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
}
```

**Response**:
```json
{
  "order_id": "KTR-BFA7DE6482",
  "amount_with_tax": 420.0,
  "amount_without_tax": 400.0,
  "kot_code": "KTR-23",
  "order_type": "DINEIN"
}
```

---

## 3. EDC Payment API

### Initiate EDC Payment
Push a payment request to the PhonePe EDC terminal.
**Note**: `merchant_id` and `terminal_id` are automatically resolved based on the `store_id`.

**Endpoint**: `POST /payments/edc/init`

**Request Body**:
```json
{
  "order_id": "KTR-D649054EBF",
  "amount_paise": 42000,
  "store_id": "teststore1"
}
```

**Response**:
```json
{
  "order_id": "KTR-D649054EBF",
  "transaction_id": "KTR-D649054EBF",
  "amount": 42000,
  "message": "Your request has been successfully completed.",
  "provider": "PhonePe EDC"
}
```

### Check EDC Status
Check the status of an EDC transaction. If successful, this also triggers the KDS sync.

**Endpoint**: `GET /payments/edc/status/{order_id}`

**Response (Success)**:
```json
{
  "order_id": "KTR-567FFED6E4",
  "transaction_id": "KTR-567FFED6E4",
  "payment_status": "COMPLETED",
  "provider_code": "SUCCESS",
  "payment_mode": "CARD",
  "reference_number": "992970454997",
  "amount": 0,
  "provider_raw": {
    "code": "SUCCESS",
    "data": {
      "status": "SUCCESS",
      ...
    },
    "success": true
  },
  "kds_invoice_id": "15833",
  "kds_status": "POSTED",
  "kot_code": "KTR-20"
}
```

---

## 4. QR Payment API

### Initiate QR Payment
Generate a dynamic QR code for the order.

**Endpoint**: `POST /payments/qr/init`

**Request Body**:
```json
{
  "order_id": "KTR-BFA7DE6482",
  "amount_paise": 42000,
  "store_id": "KTRVER01"
}
```

**Response**:
```json
{
  "order_id": "KTR-BFA7DE6482",
  "transaction_id": "KTR-BFA7DE6482",
  "qr_string": "upi://pay?...",
  "expires_at": "2024-..."
}
```

### Check QR Status
Check the status of a QR transaction.

**Endpoint**: `GET /payments/qr/status/{order_id}`

**Response (Success)**:
```json
{
  "order_id": "KTR-BFA7DE6482",
  "payment_status": "COMPLETED",
  "provider_code": "PAYMENT_SUCCESS",
  "provider_raw": {
    "code": "PAYMENT_SUCCESS",
    "data": {
      "paymentState": "COMPLETED",
      ...
    },
    "success": true
  },
  "kds_invoice_id": "15835",
  "kds_status": "POSTED",
  "kot_code": "KTR-23"
}
```

---

## 5. Cash Payment API

### Initiate Cash Payment
Record a cash payment for an order. This immediately marks the order as COMPLETED and syncs to KDS.

**Endpoint**: `POST /payments/cash/init`

**Request Body**:
```json
{
  "order_id": "KTR-F5C9871E0C",
  "amount_paise": 42000,
  "store_id": "KTRVER01"
}
```

**Response**:
```json
{
  "order_id": "KTR-F5C9871E0C",
  "payment_status": "COMPLETED",
  "provider_code": "SUCCESS",
  "provider_message": "Cash Payment Recorded",
  "kds_status": "POSTED"
}
```
