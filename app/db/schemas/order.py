from pydantic import BaseModel, Field, ConfigDict, StringConstraints
from typing import Annotated, List, Optional
from app.db.models.order import OrderType, PaymentStatus

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
    # Mixed orders: per-line DINEIN / TAKEAWAY. Omit to use the order's order_type.
    order_type: Optional[OrderType] = None
    # Free-text kitchen options ("Extra benne", "Less spicy") and a note; sent to Petpooja
    # as the item's special instructions. Not priced.
    options: List[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=8
    )
    note: Optional[str] = Field(default=None, max_length=200)
    model_config = ConfigDict(populate_by_name=True)

class OrderCreateRequest(BaseModel):
    channel: str
    # Order-level type; also the default for lines without their own order_type.
    order_type: OrderType
    items: List[OrderItemCreate]
    total_amount_include_tax: float
    total_amount_exclude_tax: float
    # Takeaway charges apply to TAKEAWAY lines only (per-line order_type, else order_type).
    # Optional; server recalculates — if you send non-zero values they must match within tolerance.
    takeaway_charges_without_tax: float = 0
    takeaway_charges_with_tax: float = 0
    discount_id: Optional[int] = None

class OrderCreateResponse(BaseModel):
    order_id: str
    amount_with_tax: float = Field(serialization_alias="total_amount_include_tax")
    amount_without_tax: float = Field(serialization_alias="total_amount_exclude_tax")
    payment_status: PaymentStatus
    order_type: OrderType
    takeaway_charges_without_tax: float
    takeaway_charges_with_tax: float

    model_config = ConfigDict(populate_by_name=True)
