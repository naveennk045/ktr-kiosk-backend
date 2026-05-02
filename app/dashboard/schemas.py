from pydantic import BaseModel
from typing import List, Literal, Optional
from datetime import date, datetime
from app.db.models.order import OrderType, PaymentStatus

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


class OrderGridItem(BaseModel):
    orderRefId: str
    orderId: str
    kotCode: str
    orderType: OrderType
    paymentType: Optional[str] = None
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
    takeaway_charges_without_tax: float = 0
    takeaway_charges_with_tax: float = 0
    cash_collected_by_staff_name: Optional[str] = None


# ─── Item-wise Analytics Schemas ──────────────────────────────────────────────

class ItemRankEntry(BaseModel):
    """A single item with aggregated order statistics."""
    sku: str
    item_name: str
    total_quantity: int
    total_revenue: float
    order_count: int  # number of distinct orders containing this item


class ItemTopResponse(BaseModel):
    """Top N items ranked by quantity sold."""
    period: DashboardPeriod
    limit: int
    items: List[ItemRankEntry]


class ItemDailyCount(BaseModel):
    """Quantity of a specific item ordered on a given date."""
    date: date
    sku: str
    item_name: str
    total_quantity: int
    order_count: int


class ItemDailyResponse(BaseModel):
    """Per-day breakdown of item quantities. Optionally filtered by SKU."""
    period: DashboardPeriod
    sku_filter: Optional[str]
    rows: List[ItemDailyCount]


class ItemSummaryEntry(BaseModel):
    """Full summary stats for a single item across a period."""
    sku: str
    item_name: str
    total_quantity: int
    total_revenue: float
    order_count: int
    avg_quantity_per_order: float


class ItemSummaryResponse(BaseModel):
    """All items with their aggregated statistics for the period."""
    period: DashboardPeriod
    total_items_sold: int  # sum of all quantities
    unique_items: int
    items: List[ItemSummaryEntry]
