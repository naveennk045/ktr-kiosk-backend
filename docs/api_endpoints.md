# Restaurant Kiosk API Documentation

## Base URL
```
http://127.0.0.1:8000
```

## Overview
This API provides endpoints for managing and retrieving menu data for a restaurant kiosk system. It supports fetching categories and menu items with their customizations and add-ons.

---

## Endpoints

### 1. Get All Categories

Retrieves a list of all available food categories.

**Endpoint:** `GET /menu/categories`

**Request Parameters:** None

**Headers:** None required

**Response Status:** `200 OK`

**Response Body:**
```json
[
  {
    "_id": "string",
    "name": "string",
    "description": "string",
    "legacy_id": "number"
  }
]
```

**Example Request:**
```bash
curl -X GET http://127.0.0.1:8000/menu/categories
```

**Example Response:**
```json
[
  {
    "_id": "69009091aa68762eb72c42bf",
    "name": "Indian",
    "description": "Traditional Indian cuisine",
    "legacy_id": 1
  },
  {
    "_id": "69009091aa68762eb72c42c0",
    "name": "Chinese",
    "description": "Authentic Chinese dishes",
    "legacy_id": 2
  },
  {
    "_id": "69009091aa68762eb72c42c1",
    "name": "Italian",
    "description": "Classic Italian favorites",
    "legacy_id": 3
  }
]
```

---

### 2. Get Items by Category

Retrieves all menu items for a specific category, including customization options and available add-ons.

**Endpoint:** `GET /menu/categories/{category_id}/items`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| category_id | integer | Yes | The legacy ID of the category |

**Request Headers:** None required

**Response Status:** `200 OK`

**Response Body:**
```json
[
  {
    "_id": "string",
    "name": "string",
    "description": "string",
    "price": "number",
    "imageSrc": "string",
    "category": {
      "id": "string",
      "collection": "string"
    },
    "customizations": [
      {
        "id": "string",
        "name": "string",
        "type": "string",
        "options": [
          {
            "value": "string",
            "label": "string",
            "price_impact": "number"
          }
        ],
        "required": "boolean"
      }
    ],
    "addons": [
      {
        "id": "string",
        "name": "string",
        "price": "number"
      }
    ],
    "legacy_id": "number"
  }
]
```

**Example Request:**
```bash
curl -X GET http://127.0.0.1:8000/menu/categories/2/items
```

**Example Response:**
```json
[
  {
    "_id": "69009093aa68762eb72c42d5",
    "name": "Kung Pao Chicken",
    "description": "Stir-fried chicken with peanuts and vegetables",
    "price": 11.99,
    "imageSrc": "/Images/kung-pao-chicken.jpg",
    "category": {
      "id": "69009091aa68762eb72c42c0",
      "collection": "categories"
    },
    "customizations": [
      {
        "id": "spice_level",
        "name": "Spice Level",
        "type": "radio",
        "options": [
          {
            "value": "mild",
            "label": "Mild",
            "price_impact": 0.0
          },
          {
            "value": "medium",
            "label": "Medium",
            "price_impact": 0.0
          },
          {
            "value": "hot",
            "label": "Hot",
            "price_impact": 0.0
          },
          {
            "value": "extra_hot",
            "label": "Extra Hot",
            "price_impact": 0.5
          }
        ],
        "required": true
      }
    ],
    "addons": [
      {
        "id": "spring_roll",
        "name": "Spring Roll",
        "price": 2.99
      },
      {
        "id": "fortune_cookie",
        "name": "Fortune Cookie",
        "price": 0.5
      },
      {
        "id": "coke",
        "name": "Coca-Cola",
        "price": 2.5
      }
    ],
    "legacy_id": 13
  }
]
```

---

## Data Models

### Category

| Field | Type | Description |
|-------|------|-------------|
| _id | string | Unique identifier (MongoDB ObjectId) |
| name | string | Category name |
| description | string | Category description |
| legacy_id | integer | Legacy numeric identifier |

### Menu Item

| Field | Type | Description |
|-------|------|-------------|
| _id | string | Unique identifier (MongoDB ObjectId) |
| name | string | Item name |
| description | string | Item description |
| price | number | Base price of the item |
| imageSrc | string | Path to item image |
| category | object | Reference to parent category |
| customizations | array | Available customization options |
| addons | array | Available add-on items |
| legacy_id | integer | Legacy numeric identifier |

### Customization

| Field | Type | Description |
|-------|------|-------------|
| id | string | Customization identifier |
| name | string | Display name for customization |
| type | string | Input type (e.g., "radio", "checkbox") |
| options | array | Available options for this customization |
| required | boolean | Whether selection is mandatory |

### Customization Option

| Field | Type | Description |
|-------|------|-------------|
| value | string | Option value identifier |
| label | string | Display label |
| price_impact | number | Price adjustment (positive or negative) |

### Add-on

| Field | Type | Description |
|-------|------|-------------|
| id | string | Add-on identifier |
| name | string | Add-on name |
| price | number | Additional price for this add-on |

---

## Categories Available

The system currently supports the following categories:

1. **Indian** - Traditional Indian cuisine
2. **Chinese** - Authentic Chinese dishes
3. **Italian** - Classic Italian favorites
4. **Mexican** - Spicy Mexican delights
5. **American** - American comfort food
6. **Japanese** - Japanese specialties
7. **Thai** - Thai cuisine
8. **Mediterranean** - Mediterranean favorites
9. **Desserts** - Sweet treats
10. **Beverages** - Drinks and refreshments

---

## Customization Types

### Spice Level
Applied to various dishes (Indian, Chinese, Thai items)
- Mild (no additional charge)
- Medium (no additional charge)
- Hot (no additional charge)
- Extra Hot (+$0.50)

### Protein Choice
Available for noodles and rice dishes
- Chicken (no additional charge)
- Beef (+$1.50)
- Shrimp (+$2.00)
- Tofu (-$0.50)

### Dumpling Filling
- Pork (no additional charge)
- Chicken (no additional charge)
- Vegetable (-$0.50)

---

## Common Add-ons

- Spring Roll - $2.99
- Fortune Cookie - $0.50
- Extra Sauce - $1.00
- Coca-Cola - $2.50
- Sprite - $2.50
- Bottled Water - $1.50
- Iced Tea - $2.99

---

## Error Handling

The API follows standard HTTP status codes:

| Status Code | Description |
|-------------|-------------|
| 200 | Success - Request completed successfully |
| 400 | Bad Request - Invalid parameters |
| 404 | Not Found - Category or item not found |
| 500 | Internal Server Error - Server-side error |

---

## Notes

- All prices are in USD
- The `price_impact` field in customization options indicates how the selection affects the base price
- The `legacy_id` field is maintained for backward compatibility
- Images are served from the `/Images/` directory relative to the application root
- Category references use MongoDB ObjectId format