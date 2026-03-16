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
            # addongroups: active groups only, with inactive addongroupitems filtered out
            "addongroups": self._map_addongroups(),
            "optionSets": [],
            "discounts": [],
            "memberships": [],
            "taxTypes": self._map_taxes(),
        }

    # ------------------------------------------------------------------ #
    # Taxes
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # Categories
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # Add-on Groups
    # ------------------------------------------------------------------ #
    def _map_addongroups(self) -> List[Dict]:
        """
        Map Petpooja addongroups[] → filtered addongroups[].

        - Inactive groups (active != "1") are skipped entirely.
        - Inactive addongroupitems inside active groups are also filtered out.
          This is important because PetPooja updates menus frequently and
          inactive items must not appear in the kiosk.
        """
        result = []
        for ag in self.pp_data.get("addongroups", []):
            if str(ag.get("active")) != "1":
                continue
            # Deep copy to avoid mutating the raw response
            ag_mapped = {
                "addongroupid": str(ag.get("addongroupid")),
                "addongroup_name": ag.get("addongroup_name"),
                "addongroup_rank": ag.get("addongroup_rank"),
                "active": ag.get("active"),
                "addongroupitems": [
                    {
                        "addonitemid": str(i.get("addonitemid")),
                        "addonitem_name": i.get("addonitem_name"),
                        "addonitem_price": str(i.get("addonitem_price", "0")),
                        "addonitem_rank": i.get("addonitem_rank"),
                        "active": i.get("active"),
                        "attributes": i.get("attributes"),
                    }
                    for i in ag.get("addongroupitems", [])
                    if str(i.get("active")) == "1"
                ],
            }
            result.append(ag_mapped)
        return result

    # ------------------------------------------------------------------ #
    # Items
    # ------------------------------------------------------------------ #
    def _map_items(self) -> List[Dict]:
        """
        Map Petpooja items[] → internal items[].

        - Inactive items (active != "1") are skipped.
        - All existing frontend-compatible fields are preserved unchanged.
        - variation[]: active only, PetPooja field names preserved.
          NOTE: When itemallowvariation=1, the base item price is "0".
          The real price comes from the customer's chosen variation.
        - addon[]: references to addongroup IDs with min/max selection rules.
        - itemallowvariation / itemallowaddon flags so the frontend knows
          which items need the customer to make a choice before ordering.
        """
        result = []
        for item in self.pp_data.get("items", []):
            if str(item.get("active")) != "1":
                continue

            tax_ids = item.get("item_tax", "").split(",") if item.get("item_tax") else []
            tax_ids = [t.strip() for t in tax_ids if t.strip()]

            attr_id = str(item.get("item_attributeid"))
            tag_ids = [_ATTR_TO_TAG[attr_id]] if attr_id in _ATTR_TO_TAG else []

            # Active variations only — field names kept exactly as PetPooja sends them.
            # Each variation: { id, variationid, name, groupname, price, active,
            #                   item_packingcharges, variationrank, addon, variationallowaddon }
            active_variations = [
                var for var in item.get("variation", [])
                if str(var.get("active")) == "1"
            ]

            # item.addon[]: list of { addon_group_id, addon_item_selection_min,
            #                         addon_item_selection_max }
            # Cross-reference with catalog["addongroups"] by addongroupid to get item details.
            addon_refs = item.get("addon", [])

            allow_variation = str(item.get("itemallowvariation")) == "1"
            allow_addon = str(item.get("itemallowaddon")) == "1"

            result.append({
                # ---- Original frontend-compatible fields (unchanged) ----
                "itemId": str(item.get("itemid")),
                "skuCode": str(item.get("itemid")),
                "itemName": item.get("itemname"),
                # When variations exist, base price is 0; use variation price instead.
                "price": float(item.get("price", 0.0)),
                "taxTypeIds": tax_ids,
                "categoryId": str(item.get("item_categoryid")),
                "isPriceIncludesTax": False,
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
                # ---- Variation & add-on support ----
                # True when the customer MUST choose a size/variant before ordering.
                "itemallowvariation": allow_variation,
                # variation[]: each has id, variationid, name, groupname, price, ...
                "variation": active_variations,
                # True when the customer CAN add optional extras.
                "itemallowaddon": allow_addon,
                # addon[]: [{ addon_group_id, addon_item_selection_min, addon_item_selection_max }]
                # Resolve the full options via catalog["addongroups"][addongroupid].
                "addon": addon_refs,
            })

        return result
