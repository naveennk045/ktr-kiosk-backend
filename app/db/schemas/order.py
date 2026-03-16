from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from app.db.models.order import OrderType

class AddonItemCreate(BaseModel):
    """
    Represents a single add-on the customer chose for an item.
    addon_item_id: the addonitemid from PetPooja addongroups[].addongroupitems[]
    quantity: how many of this addon (almost always 1)
    """
    addon_item_id: str
    quantity: int = 1


class OrderItemCreate(BaseModel):
    sku_code: str = Field(..., alias="item_skuid")
    quantity: int
    # variation_id: the 'id' field from item.variation[] (the row id, NOT variationid).
    # Send this when the item has itemallowvariation=true and the customer picked a size.
    variation_id: Optional[str] = None
    # addon_items: list of add-ons the customer selected for this item.
    # Send this when the item has itemallowaddon=true.
    addon_items: Optional[List[AddonItemCreate]] = []
    model_config = ConfigDict(populate_by_name=True)

class OrderCreateRequest(BaseModel):
    channel: str
    order_type: OrderType
    items: List[OrderItemCreate]
    total_amount_include_tax: float
    total_amount_exclude_tax: float

class OrderCreateResponse(BaseModel):
    order_id: str
    amount_with_tax: float = Field(serialization_alias="total_amount_include_tax")
    amount_without_tax: float = Field(serialization_alias="total_amount_exclude_tax")
    kot_code: str
    order_type: OrderType

    model_config = ConfigDict(populate_by_name=True)