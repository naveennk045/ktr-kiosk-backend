from pydantic import BaseModel, Field, ConfigDict
from typing import List
from app.db.models.order import OrderType

class OrderItemCreate(BaseModel):
    sku_code: str = Field(..., alias="item_skuid")
    quantity: int
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