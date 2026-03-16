from pydantic import BaseModel, Field
from datetime import datetime
from typing import List

class ItemAvailabilityUpdate(BaseModel):
    sku_code: str = Field(..., description="The unique Petpooja itemId/skuCode")
    is_available: bool = Field(..., description="ON/OFF status")

class ItemAvailabilityResponse(BaseModel):
    sku_code: str
    is_available: bool
    updated_at: datetime

    class Config:
        from_attributes = True
