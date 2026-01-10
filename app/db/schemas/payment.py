from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from app.db.models.order import PaymentStatus, KdsStatus


class QRInitiateRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., ge=1)
    store_id: str | None = None


class QRInitiateResponse(BaseModel):
    order_id: str
    transaction_id: str
    qr_string: str | None = None
    expires_at: datetime | None = None
    provider: str = "PhonePe"


class EDCInitiateRequest(BaseModel):
    """Minimal EDC request - frontend only sends these fields"""
    order_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., ge=1)
    store_id: str = Field(..., min_length=1)


class EDCInitiateResponse(BaseModel):
    """EDC response after pushing payment to terminal"""
    order_id: str
    transaction_id: str
    amount: int
    message: str
    provider: str = "PhonePe EDC"


class CashInitiateRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., ge=1)
    store_id: str | None = None
    pin: str = Field(..., min_length=1)




class StatusResponse(BaseModel):
    order_id: str
    payment_status: PaymentStatus
    provider_code: str | None = None
    provider_message: str | None = None
    provider_raw: dict | None = None
    kds_invoice_id: Optional[str] = None
    kds_status: KdsStatus  # NEW
    kot_code: str | None = None  # NEW

    model_config = ConfigDict(from_attributes=True)


class EDCStatusResponse(BaseModel):
    order_id: str
    transaction_id: str
    payment_status: PaymentStatus
    provider_code: str | None = None
    payment_mode: str | None = None
    reference_number: str | None = None
    amount: int | None = None
    payment_state: str | None = None
    provider_raw: dict | None = None
    kds_invoice_id: Optional[str] = None
    kds_status: KdsStatus  # NEW
    kot_code: str | None = None  # NEW

    model_config = ConfigDict(from_attributes=True)
