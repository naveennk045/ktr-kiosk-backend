from pydantic import BaseModel, Field
from datetime import datetime
from app.db.models.order import PaymentStatus  # Import your Enum

class QRInitiateRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., ge=1)

class QRInitiateResponse(BaseModel):
    order_id: str
    transaction_id: str
    qr_string: str | None = None
    expires_at: datetime | None = None
    provider: str = "PhonePe"

class StatusResponse(BaseModel):
    order_id: str
    payment_status: PaymentStatus
    provider_code: str | None = None
    provider_message: str | None = None
    provider_raw: dict | None = None

class EDCInitiateRequest(BaseModel):
    """Minimal EDC request - frontend only sends these two fields"""
    order_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., ge=1)


class EDCInitiateResponse(BaseModel):
    """EDC response after pushing payment to terminal"""
    order_id: str
    transaction_id: str
    amount: int
    message: str
    provider: str = "PhonePe EDC"