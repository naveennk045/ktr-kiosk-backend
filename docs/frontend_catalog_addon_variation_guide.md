# Frontend Guide: PetPooja Add-ons & Variations Integration

This guide explains how the frontend kiosk application should handle PetPooja variations (Sizes, Choices) and add-ons (Extra Cheese, Toppings) using the newly updated catalog and order submission APIs.

---

## 1. Catalog Changes (Fetch Menu)

When you pull the menu from `GET /api/catalog`, you will now see new flags and fields attached to each item.

### The New Flags

Every item now has two critical boolean flags to drive your UI:
- `itemallowvariation`: If `true`, the UI **MUST** prompt the user to select a variation before adding the item to the cart. 
- `itemallowaddon`: If `true`, the UI **CAN** prompt the user to optionally select add-ons.

> **⚠️ CRITICAL: Base Price Handling for Variations**
> If an item has `itemallowvariation: true`, its base `price` field will usually be `0`. The *actual* price comes from the array of variations. 
> You must display the price of the variation they select, not the base item price.

### Example Item Payload

```json
{
  "itemId": "10550557",
  "skuCode": "10550557",
  "itemName": "Cheese Spaghetti",
  "price": 0.0,
  "itemallowvariation": true,            // <-- Show Variation Modal 
  "itemallowaddon": true,                // <-- Show Add-on Options
  
  // Array of available sizes/choices
  "variation": [
    {
      "id": "10581116",                  // <-- STORE THIS ID 
      "variationid": "12049",
      "name": "Half",
      "groupname": "Size",
      "price": "400.00"                  // <-- Display this price
    },
    {
      "id": "10581117",                  // <-- STORE THIS ID 
      "variationid": "12049",
      "name": "Full",
      "groupname": "Size",
      "price": "600.00"                  // <-- Display this price
    }
  ],
  
  // Link to add-on groups
  "addon": [
    {
      "addon_group_id": "11899",
      "addon_item_selection_min": "0",  // Usually 0 (optional)
      "addon_item_selection_max": "1"
    }
  ]
}
```

### Finding Add-on Details

If an item has `itemallowaddon: true`, look at its `addon` array to get the `addon_group_id`.
Then, look at the root of the catalog payload inside the `addongroups` array to find the matching group and its choices.

```json
// Inside the root catalog payload
"addongroups": [
  {
    "addongroupid": "11899",
    "addongroup_name": "Toppings",
    "addongroupitems": [
      {
        "addonitemid": "61853",           // <-- STORE THIS ID
        "addonitem_name": "Onion",
        "addonitem_price": "20.0"         // <-- Extra cost to add
      },
      {
        "addonitemid": "61854",           // <-- STORE THIS ID
        "addonitem_name": "Cheese",
        "addonitem_price": "40.0"         // <-- Extra cost to add
      }
    ]
  }
]
```

---

## 2. Order Submission Changes (Create Order)

When sending the items to `POST /api/orders`, you must now pass the selected choices inside the `items` array.

### The New `OrderItemCreate` Schema

For items that had variations or addons selected, simply attach the new `variation_id` and `addon_items` fields.

* Existing endpoints without variations/addons will still work (these fields are optional).
* **IMPORTANT**: For `variation_id`, you must send the unique row `"id"` (e.g. `"10581116"`), NOT the categorical `"variationid"`.

### Example Request Payload

```json
{
  "channel": "KIOSK",
  "order_type": "DINEIN",
  "total_amount_include_tax": 460.0,
  "total_amount_exclude_tax": 460.0,
  "items": [
    {
      "item_skuid": "10550557",
      "quantity": 1,
      // Pass the selected Variation ID (the "id" field inside variation[])
      "variation_id": "10581116",  
      "addon_items": [
        {
          // Pass the selected Add-on Item ID (the "addonitemid" field)
          "addon_item_id": "61853",
          "quantity": 1
        },
        {
          "addon_item_id": "61854",
          "quantity": 1
        }
      ]
    }
  ]
}
```

### Cart Representation Note
If a user adds the *same base item* (e.g., Cheese Spaghetti) but with a *different* variation (e.g., "Full" instead of "Half") or *different* add-ons, your frontend cart should treat them as **two separate line items** rather than merging the quantities together.

---

### Backend Handling 
You don't need to calculate any of the Petpooja payload strings! As long as you submit the `variation_id` and `addon_item_id`(s), the backend will automatically look up the correct names, structure the sub-arrays, and calculate the Petpooja totals.
