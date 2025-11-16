# KTR Kiosk API Documentation

_This API allows a client (like a Kiosk or POS) to fetch the product catalog, create orders, and manage payments via QR or EDC terminals._

## Base URL

- For local testing: `http://127.0.0.1:8000/`
- For remote/ngrok dev: `https://unfogging-traditionally-briley.ngrok-free.dev/`

***

## 1. Get Catalog

**Endpoint:** `GET /catalog`

Retrieve the list of categories, items, item tags, taxes, and charges available for ordering.

### Request

- **Query Parameters:**
    - `channel` (string, required): e.g., "Palas Kiosk" (useful for kiosk-specific configurations)

_Example:_

```
GET /catalog?channel=Palas%20Kiosk
```


### Response

- **Fields:**
    - `categories`: Array of categories
    - `itemTags`: Array of item tags (e.g., Vegetarian, Non-vegetarian)
    - `charges`: List of potential charges (e.g., order charge)
    - `items`: List of orderable items with details (id, name, price, category, tags, etc)
    - `taxTypes`: Array of applicable taxes
- **Example:**

```json
{
  "categories": [
    {"categoryId": "68e778dd0c42e107fdf5cf3f", "name": "BEVERAGE", ...},
    ...
  ],
  "itemTags": [
    { "itemTagId": "6868c0ab6065bace3cd952b7", "name": "Vegetarian" }, ...
  ],
  "charges": [
    { "chargeId": "68f0e00a592b7cf3428c5f0e", "name": "PC", "chargeType": "Absolute", "chargeRate": 20 }, ...
  ],
  "items": [
    { "itemId": "6868ca5d4fda6eabd33ccba2", "itemName": "Davanagere Benne Sada Dose", "price": 110, ... },
    ...
  ],
  "taxTypes": [
    { "taxTypeId": "6868c05ede387c9d22a94396", "name": "CGST", "percentage": 2.5 }, ...
  ]
}
```


***

## 2. Create Order

**Endpoint:** `POST /orders`

Create a new customer order.

### Request

- **Headers:**
    - `Content-Type: application/json`
- **Body JSON:**
    - `channel` (string, required)
    - `items` (array, required): Each item has `item_skuid` (string/int) and `quantity` (int)
    - `total_amount_include_tax` (number, required): Final amount, including tax
    - `total_amount_exclude_tax` (number, required): Final amount, excluding tax

_Example:_

```json
{
  "channel": "Palas Kiosk",
  "items": [
    { "item_skuid": "7", "quantity": 2 },
    { "item_skuid": "27", "quantity": 1 }
  ],
  "total_amount_include_tax": 420.0,
  "total_amount_exclude_tax": 400.0
}
```


### Response

- **Fields:**
    - `order_id` (string): Unique order identifier (e.g., "ord-94185cc0e24540fb99f4492225cec6ed")
    - `total_amount_include_tax`: Echoed input
    - `total_amount_exclude_tax`: Echoed input
    - `kot_code`: Internal code (useful for kitchen display)
- **Example:**

```json
{
  "order_id": "ord-94185cc0e24540fb99f4492225cec6ed",
  "total_amount_include_tax": 420.0,
  "total_amount_exclude_tax": 400.0,
  "kot_code": "ktr-6"
}
```


***

## 3. Initiate QR Payment

**Endpoint:** `POST /payments/qr/init`

Starts a new QR-based payment for an order.

### Request

- **Headers:**
    - `Content-Type: application/json`
- **Body JSON:**
    - `order_id` (string, required): ID from the `/orders` endpoint
    - `amount_paise` (string/int, required): Amount in paise (not rupees!)

_Example:_

```json
{
  "order_id": "ord-b79bcd82ec7f472ab747371782ba2140",
  "amount_paise": "42000"
}
```


### Response

- **Fields:**
    - `order_id`, `transaction_id`
    - `qr_string`: UPI QR payload (can be encoded for QR code display)
    - `expires_at`: ISO timestamp (when the QR expires)
    - `provider`: e.g., "PhonePe"
- **Example:**

```json
{
  "order_id": "ord-94185cc0e24540fb99f4492225cec6ed",
  "transaction_id": "ord-94185cc0e24540fb99f4492225cec6ed",
  "qr_string": "upi://pay?pa=HIMALAYANSAVOURUAT@ybl&pn=...",
  "expires_at": "2025-11-16T09:30:47.375779Z",
  "provider": "PhonePe"
}
```


***

## 4. QR Payment Status

**Endpoint:** `GET /payments/qr/status/{order_id}`

Check if a QR payment for an order is complete.

### Request

- **Path parameter:**
    - `order_id` (string, required): The order's unique ID


### Response

- **Fields:**
    - (Same as QR initiation, may include current payment status)

***

## 5. Initiate EDC Payment

**Endpoint:** `POST /payments/edc/init`

Start a payment request to an EDC terminal (card payment).

### Request

- **Headers:**
    - `Content-Type: application/json`
- **Body JSON:**
    - `order_id` (string, required)
    - `amount_paise` (string/int, required)

_Example:_

```json
{
  "order_id": "ord-b79bcd82ec7f472ab747371782ba2140",
  "amount_paise": "42000"
}
```


### Response

- **Fields:**
    - `order_id`, `transaction_id`, `amount`, `provider`
    - `message`: Operation status
- **Example:**

```json
{
  "order_id": "ord-b12061bc58ec47aea524d230ed445d80",
  "transaction_id": "ord-b12061bc58ec47aea524d230ed445d80",
  "amount": 42000,
  "message": "Your request has been successfully completed.",
  "provider": "PhonePe EDC"
}
```


***

## 6. EDC Payment Status

**Endpoint:** `GET /payments/edc/status/{order_id}`

Check the latest status for an EDC payment.

### Request

- **Path parameter:**
    - `order_id` (string, required)


### Response

- **Fields:**
    - `order_id`, `transaction_id`, `payment_status` (e.g., "PENDING"), `provider_code`, `payment_mode`, `reference_number`, `amount`, `payment_state`, `provider_raw` (raw response from provider), `kds_invoice_id`, `kds_status`, `kot_code`
- **Example:**

```json
{
  "order_id": "ord-b12061bc58ec47aea524d230ed445d80",
  "transaction_id": "ord-b12061bc58ec47aea524d230ed445d80",
  "payment_status": "SUCCESS",
  "provider_code": "SUCCESS",
  "payment_mode": null,
  "reference_number": null,
  "amount": null,
  "payment_state": null,
  "provider_raw": {
    "success": true,
    "code": "SUCCESS",
    "message": "Your request has been successfully completed.",
    "data": {
      "merchantId": "HIMALAYANSAVOURUAT",
      "storeId": "teststore1",
      "terminalId": "testterminal1",
      "orderId": "ord-b12061bc58ec47aea524d230ed445d80",
      "transactionId": "ord-b12061bc58ec47aea524d230ed445d80",
      "status": "PENDING",
      "responseCode": "null",
      "timestamp": 1763285467669
    }
  },
  "kds_invoice_id": null,
  "kds_status": "NOT_POSTED",
  "kot_code": "ktr-7"
}
```


***

## Quick Reference Table

| Route | Method | Purpose |
| :-- | :-- | :-- |
| `/catalog` | GET | fetch menu/catalog |
| `/orders` | POST | create new order |
| `/payments/qr/init` | POST | start QR payment |
| `/payments/qr/status/{order_id}` | GET | get QR pay status |
| `/payments/edc/init` | POST | start EDC payment |
| `/payments/edc/status/{order_id}` | GET | get EDC pay status |


***

## Notes

- `amount_paise` is always required as an integer or string (e.g., 42000 for ₹420.00). Make sure order amounts are matched.
- For QR: Use `qr_string` to generate/display a QR code for UPI payment.
- EDC response `provider_raw` may hold extra debugging/state info from payment provider.
- All requests and responses are JSON.

***

If you need endpoint-specific details, error scenarios, or want a sample API workflow, let me know your exact use-case or audience and I’ll tailor the docs further.
<span style="display:none">[^1][^10][^2][^3][^4][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://insomnia.rest

[^2]: https://www.digitalocean.com/community/tutorials/how-to-create-documentation-for-your-rest-api-with-insomnia

[^3]: https://dev.to/joselatines/how-to-generate-api-documentation-with-insomnia-18fg

[^4]: https://apidog.com/blog/insomnia-api-documentation/

[^5]: https://lightrains.com/blogs/create-api-documentation-insomnia-documenter/

[^6]: https://developer.konghq.com/insomnia/

[^7]: https://github.com/insodoc/insomnia-documenter

[^8]: https://insomnia.rest/plugins

[^9]: https://insomnia.rest/features/api-mocking

[^10]: https://learning.postman.com/docs/getting-started/importing-and-exporting/importing-from-insomnia/

