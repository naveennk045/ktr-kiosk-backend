from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime

class DiscountBase(BaseModel):
    store_id: Optional[int] = None
    name: str
    application_type: str  # COUPON, AUTOMATIC, LOYALTY, REFERRAL
    code: Optional[str] = None
    discount_type: str  # PERCENTAGE, FIXED_AMOUNT, FREE_SHIPPING
    value: Optional[float] = None
    max_discount_amount: Optional[float] = None
    min_order_amount: Optional[float] = None
    usage_limit: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = True

class DiscountCreate(DiscountBase):
    pass

class DiscountUpdate(BaseModel):
    store_id: Optional[int] = None
    name: Optional[str] = None
    application_type: Optional[str] = None
    code: Optional[str] = None
    discount_type: Optional[str] = None
    value: Optional[float] = None
    max_discount_amount: Optional[float] = None
    min_order_amount: Optional[float] = None
    usage_limit: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None

class DiscountStatusUpdate(BaseModel):
    is_active: bool

class DiscountResponse(BaseModel):
    id: int
    store_id: Optional[int] = None
    name: str
    application_type: str
    code: Optional[str] = None
    discount_type: str
    value: Optional[float] = None
    max_discount_amount: Optional[float] = None
    min_order_amount: Optional[float] = None
    usage_limit: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0

    model_config = ConfigDict(from_attributes=True)

class DiscountValidateRequest(BaseModel):
    application_type: str
    code: Optional[str] = None
    cart_amount: float

class DiscountValidateResponse(BaseModel):
    valid: bool
    discount_id: Optional[int] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    discount_amount: Optional[float] = None
    message: str
