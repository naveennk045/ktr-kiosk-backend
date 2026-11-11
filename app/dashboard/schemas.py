from pydantic import BaseModel
from typing import List, Literal, Optional
from datetime import date, datetime
from app.db.models.order import OrderType, PaymentStatus

DashboardPeriod = Literal["today", "yesterday", "last_week", "all_time", "custom_range"]


class AnalyticsSummaryResponse(BaseModel):
    """Completed orders only; time window is in Asia/Kolkata (IST)."""
    period: DashboardPeriod
    from_date: Optional[date] = None
    to_date: Optional[date] = None
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
    from_date: Optional[date] = None
    to_date: Optional[date] = None
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
    from_date: Optional[date] = None
    to_date: Optional[date] = None
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
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    total_items_sold: int  # sum of all quantities
    unique_items: int
    items: List[ItemSummaryEntry]


# ─── Category-wise Analytics Schemas ──────────────────────────────────────────

class CategoryItemEntry(BaseModel):
    """A single item's aggregated sales within a category."""
    sku: str
    item_name: str
    total_quantity: int
    total_revenue: float
    order_count: int


class CategorySummaryEntry(BaseModel):
    """Aggregated sales statistics for a category, including items sold under it."""
    category_id: str
    category_name: str
    total_quantity: int
    total_revenue: float
    order_count: int
    items: List[CategoryItemEntry]


class CategorySummaryResponse(BaseModel):
    """All categories with their aggregated statistics for the period."""
    period: DashboardPeriod
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    categories: List[CategorySummaryEntry]



# ─── Customer-behaviour Insights Schemas ──────────────────────────────────────

InsightsDaypart = Literal["all", "breakfast", "lunch", "evening"]


class InsightsWindow(BaseModel):
    """Resolved IST window. `start` is null for open-ended periods (all_time)."""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    days: int  # IST calendar days covered; used for per-day rates


class InsightsKpis(BaseModel):
    orders: int
    revenue: float  # sum of order totals incl. tax (same as /analytics/summary totalRevenue)
    avg_order_value: float
    units: int  # sum of line quantities
    items_per_order: float
    takeaway_orders: int
    takeaway_share_pct: float
    timed_orders: int  # orders whose kitchen lines were all marked ready
    ready_seconds_avg: Optional[float] = None  # payment -> last line ready
    ready_seconds_median: Optional[float] = None


class InsightsOrderTypeSide(BaseModel):
    orders: int  # by the order's own order_type
    revenue: float
    units: int  # by each line's effective type (mixed orders split per line)
    avg_order_value: float


class InsightsDaypartSplit(BaseModel):
    daypart: Literal["breakfast", "lunch", "evening"]
    orders: int
    takeaway_orders: int
    takeaway_share_pct: float


class InsightsPackedItem(BaseModel):
    sku: str
    item_name: str
    quantity: int


class InsightsOrderTypes(BaseModel):
    dine_in: InsightsOrderTypeSide
    takeaway: InsightsOrderTypeSide
    by_daypart: List[InsightsDaypartSplit]
    top_takeaway_items: List[InsightsPackedItem]
    takeaway_charges_total: float  # packing charges collected, incl. tax
    mixed_orders: int  # orders with both dine-in and takeaway lines


class InsightsItem(BaseModel):
    sku: str
    item_name: str
    quantity: int
    revenue: float  # price x quantity
    order_count: int
    previous_quantity: Optional[int] = None  # null when there is no previous period


class InsightsMover(BaseModel):
    sku: str
    item_name: str
    quantity: int
    previous_quantity: int
    change_pct: Optional[float] = None  # null when the item did not sell in the previous period


class InsightsCategory(BaseModel):
    category_id: str
    category_name: str
    quantity: int
    revenue: float
    revenue_share_pct: float
    order_count: int
    order_share_pct: float  # share of all orders containing this category
    timed_lines: int
    ready_seconds_avg: Optional[float] = None  # avg per line: sent to kitchen -> ready


class InsightsHeatCell(BaseModel):
    weekday: int  # 0 = Sunday … 6 = Saturday (IST)
    hour: int  # 0–23 (IST)
    orders: int


class InsightsDailyPoint(BaseModel):
    date: date
    orders: int
    revenue: float


class InsightsHabits(BaseModel):
    """Order counts; divide by `orders` for rates."""
    orders: int
    multi_item_orders: int  # more than one unit
    customised_orders: int  # any option, note or add-on
    option_orders: int
    note_orders: int
    addon_orders: int
    discount_orders: int


class InsightsPair(BaseModel):
    sku_a: str
    item_a: str
    sku_b: str
    item_b: str
    orders: int
    share_pct: float  # share of all orders that had both


class InsightsCustomisation(BaseModel):
    option: str
    category_id: str
    category_name: str
    quantity: int
    share_pct: float  # share of that category's units ordered with this option


class InsightsSuggestion(BaseModel):
    kind: Literal["star", "up", "warn", "idea", "clock"]
    text: str


class InsightsResponse(BaseModel):
    """Customer-behaviour analytics. Completed orders only; IST windows."""
    period: DashboardPeriod
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    daypart: InsightsDaypart
    store_ids: List[int]
    window: InsightsWindow
    previous_window: Optional[InsightsWindow] = None
    kpis: InsightsKpis
    previous_kpis: Optional[InsightsKpis] = None
    order_types: InsightsOrderTypes
    best_sellers: List[InsightsItem]
    slow_movers: List[InsightsItem]
    movers: List[InsightsMover]
    categories: List[InsightsCategory]
    category_mapping_available: bool
    heatmap: List[InsightsHeatCell]
    daily: List[InsightsDailyPoint]
    habits: InsightsHabits
    pairs: List[InsightsPair]
    customisations: List[InsightsCustomisation]
    suggestions: List[InsightsSuggestion]
