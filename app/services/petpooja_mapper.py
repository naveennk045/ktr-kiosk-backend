"""
PetpoojaMapper: converts raw Petpooja Fetch Menu JSON → internal catalog format.

Extracted from CatalogService._map_petpooja_response to give each mapping
concern (taxes, categories, items) its own focused method.
"""
from typing import Any, Dict, List


# Tag IDs — Petpooja item attributes map to these internal tag identifiers
TAG_VEG_ID = "6868c0ab6065bace3cd952b7"
TAG_NON_VEG_ID = "6868c0ab6065bace3cd952b8"
TAG_EGG_ID = "6868c0ab6065bace3cd952bb"

# Attribute ID → tag mapping (1=Veg, 2=Non-Veg, 3=Egg)
_ATTR_TO_TAG: Dict[str, str] = {
    "1": TAG_VEG_ID,
    "2": TAG_NON_VEG_ID,
    "3": TAG_EGG_ID,
}

ITEM_TAGS = [
    {"itemTagId": TAG_VEG_ID, "name": "Vegetarian"},
    {"itemTagId": TAG_NON_VEG_ID, "name": "Non-vegetarian"},
    {"itemTagId": TAG_EGG_ID, "name": "Egg"},
]


class PetpoojaMapper:
    """
    Maps a raw Petpooja 'Fetch Menu' response dict to the internal catalog format.
    Matches the legacy Rista structure for frontend compatibility.

    Usage:
        catalog = PetpoojaMapper(pp_data).build()
    """

    def __init__(self, pp_data: Dict[str, Any]):
        self.pp_data = pp_data

    def build(self) -> Dict[str, Any]:
        """Orchestrate all sub-mappers and return the full internal catalog dict."""
        return {
            "categories": self._map_categories(),
            "schedules": [],
            "itemTags": ITEM_TAGS,
            "charges": [],
            "items": self._map_items(),
            "optionSets": [],
            "discounts": [],
            "memberships": [],
            "taxTypes": self._map_taxes(),
        }

    def _map_taxes(self) -> List[Dict]:
        """Map Petpooja taxes[] → internal taxTypes[]."""
        result = []
        for tx in self.pp_data.get("taxes", []):
            result.append({
                "taxTypeId": str(tx.get("taxid")),
                "name": tx.get("taxname"),
                "percentage": float(tx.get("tax", 0.0)),
                "type": tx.get("taxtype"),
            })
        return result

    def _map_categories(self) -> List[Dict]:
        """Map Petpooja categories[] → internal categories[]."""
        result = []
        for cat in self.pp_data.get("categories", []):
            result.append({
                "categoryId": str(cat.get("categoryid")),
                "name": cat.get("categoryname"),
                "subCategories": [],  # Legacy field
                "imageURL": cat.get("category_image_url", ""),
                "categoryrank": cat.get("categoryrank"),
                "active": cat.get("active"),
            })
        return result

    def _map_items(self) -> List[Dict]:
        """
        Map Petpooja items[] → internal items[].
        Items with variations are flattened — each active variation becomes its own SKU.
        Inactive items (active != "1") are skipped.
        """
        result = []
        for item in self.pp_data.get("items", []):
            if str(item.get("active")) != "1":
                continue

            tax_ids = item.get("item_tax", "").split(",") if item.get("item_tax") else []
            tax_ids = [t.strip() for t in tax_ids if t.strip()]

            attr_id = str(item.get("item_attributeid"))
            tag_ids = [_ATTR_TO_TAG[attr_id]] if attr_id in _ATTR_TO_TAG else []

            base = {
                "itemId": str(item.get("itemid")),
                "skuCode": str(item.get("itemid")),
                "itemName": item.get("itemname"),
                "price": float(item.get("price", 0.0)),
                "taxTypeIds": tax_ids,
                "categoryId": str(item.get("item_categoryid")),
                "isPriceIncludesTax": False,  # Petpooja sends exclusive prices
                "status": "Active",
                "description": item.get("itemdescription", ""),
                "type": "Simple",
                "itemTagIds": tag_ids,
                "chargeIds": [],
                "scheduleIds": [],
                "measuringUnit": "ea",
                "itemNature": "Service",
                "denyDiscount": False,
                "imageURL": item.get("item_image_url", ""),
                "optionSetIds": [],
            }

            variations = item.get("variation", [])
            if not variations:
                result.append(base)
            else:
                # Flatten: each active variation becomes an independent SKU
                for var in variations:
                    if str(var.get("active")) != "1":
                        continue
                    var_item = base.copy()
                    var_item["itemId"] = str(var.get("id"))
                    var_item["skuCode"] = str(var.get("id"))
                    var_item["itemName"] = f"{item.get('itemname')} ({var.get('name')})"
                    var_item["price"] = float(var.get("price", 0.0))
                    result.append(var_item)

        return result
