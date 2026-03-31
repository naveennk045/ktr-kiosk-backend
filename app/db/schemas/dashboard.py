from pydantic import BaseModel
from typing import List, Literal, Optional
from datetime import datetime
from app.db.models.order import PaymentStatus

DashboardPeriod = Literal["today", "yesterday", "last_week", "all_time"]

class AnalyticsSummaryResponse(BaseModel):
    """Completed orders only; time window is in Asia/Kolkata (IST)."""
    period: DashboardPeriod
    totalRevenue: float
    totalOrders: int
    dineInOrders: int
    takeAwayOrders: int
    upiRupees: float
    cardRupees: float
    cashRupees: float
    manualRupees: float

class OrderGridItem(BaseModel):
    orderRefId: str
    location: str
    amount: float
    paymentStatus: PaymentStatus
    erpStatus: str  # derived from kds_status
    itemsSummary: str
    createdAt: datetime

class OrderGridResponse(BaseModel):
    content: List[OrderGridItem]
    totalPages: int
    totalElements: int

class OrderDetailResponse(BaseModel):
    orderRefId: str
    location: str
    amount: float
    paymentStatus: PaymentStatus
    erpStatus: str
    items: list
    paymentMeta: Optional[dict] = None
    createdAt: datetime
