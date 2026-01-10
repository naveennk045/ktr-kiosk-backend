from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.db.models.order import PaymentStatus

class AnalyticsSummaryResponse(BaseModel):
    totalRevenue: float
    totalOrders: int
    pendingPayments: int
    syncFailures: int

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
