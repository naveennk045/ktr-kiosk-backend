from collections import defaultdict
from collections import deque
import asyncio
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
from typing import List, Optional
from zoneinfo import ZoneInfo

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import asc, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis_client, get_store_context
from app.db.models.cash_pin import CashPin
from app.db.models.order import (
    KdsStatus,
    Order,
    OrderItem,
    OrderType,
    PaymentMethod,
    PaymentStatus,
)
from app.db.models.store import (
    KioskTerminal,
    Store,
    StorePetpoojaCredentials,
    StorePhonePeCredentials,
    StorePinelabsCredentials,
)
from app.dashboard.schemas import DashboardPeriod
from app.services.store_cache import invalidate_store_cache

router = APIRouter(prefix="/admin", tags=["admin"])
LOG_FILE_PATH = Path("app.log")
LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>[^-]+?)\s+-\s+\[(?P<level>[A-Z]+)\]\s+-\s+(?P<logger>[^-]+?)\s+-\s+(?P<message>.*)$"
)
IST = ZoneInfo("Asia/Kolkata")


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    """Return last N lines from a UTF-8 text file."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=max_lines)]


def _parse_log_line(line: str) -> dict:
    """
    Parse standard app log format into frontend-friendly fields.
    Now supports JSON structured logging as the primary format,
    falling back to legacy text matching for older lines.
    """
    try:
        data = json.loads(line)
        # Ensure 'raw' is set for frontend consistency
        data["raw"] = line
        return data
    except Exception:
        pass

    # Fallback for old text logs
    match = LOG_LINE_PATTERN.match(line)
    if not match:
        return {
            "timestamp": None,
            "level": "UNKNOWN",
            "logger": None,
            "message": line,
            "raw": line,
        }
    data = match.groupdict()
    return {
        "timestamp": data["timestamp"].strip(),
        "level": data["level"].strip(),
        "logger": data["logger"].strip(),
        "message": data["message"],
        "raw": line,
    }


class KioskTerminalItem(BaseModel):
    id: int
    terminal_id: str
    pinelabs_store_id: str
    mid_on_device: str | None = None
    label: str | None = None
    is_active: bool

    class Config:
        from_attributes = True


class KioskConfigResponse(BaseModel):
    store_id: int = Field(description="Internal numeric store id")
    store_code: str
    store_name: str
    pinelabs_configured: bool = Field(
        description="Whether shared PineLabs API credentials exist for this store"
    )
    terminals: List[KioskTerminalItem]


class StoreDetailResponse(BaseModel):
    store_id: int = Field(description="Internal numeric store id")
    store_code: str
    store_name: str
    is_active: bool
    petpooja_configured: bool
    phonepe_configured: bool
    pinelabs_configured: bool
    terminals: List[KioskTerminalItem]


class StoreAnalyticsItem(BaseModel):
    store_id: int
    store_code: str
    store_name: str
    totalRevenue: float
    totalOrders: int
    dineInOrders: int
    takeAwayOrders: int
    upiRupees: float
    cardRupees: float
    cashRupees: float


class MultiStoreAnalyticsResponse(BaseModel):
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
    stores: List[StoreAnalyticsItem]


class TopOrderedItem(BaseModel):
    itemName: str
    quantity: int
    revenue: float


class StoreOwnerInsight(BaseModel):
    store_id: int
    store_code: str
    store_name: str
    totalRevenue: float
    totalOrders: int
    averageOrderValue: float
    dineInOrders: int
    takeAwayOrders: int
    upiRupees: float
    cardRupees: float
    cashRupees: float
    topItems: List[TopOrderedItem]
    topChannel: str | None = None


class OwnerInsightsResponse(BaseModel):
    period: DashboardPeriod
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    totalRevenue: float
    totalOrders: int
    averageOrderValue: float
    stores: List[StoreOwnerInsight]


class TerminalSettlement(BaseModel):
    terminalId: str
    cardAmount: float
    cardTxnCount: int


class StaffCashSettlement(BaseModel):
    staffName: str
    cashAmount: float
    cashTxnCount: int


class AccountingSettlementStore(BaseModel):
    store_id: int
    store_code: str
    grossSales: float
    netSales: float
    totalTax: float
    takeawayChargesCollected: float
    totalUpi: float
    totalCard: float
    totalCash: float
    pineLabsSettlement: List[TerminalSettlement]
    cashSettlement: List[StaffCashSettlement]


class AccountingSettlementResponse(BaseModel):
    period: DashboardPeriod
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    stores: List[AccountingSettlementStore]



class AdminTransactionItem(BaseModel):
    orderId: str
    store_id: int
    store_code: str
    store_name: str
    createdAt: datetime
    orderType: OrderType
    paymentMethod: PaymentMethod | None = None
    paymentStatus: PaymentStatus
    kdsStatus: KdsStatus
    amount: float
    channel: str
    terminalId: str | None = None
    kotCode: str


class AdminTransactionsResponse(BaseModel):
    content: List[AdminTransactionItem]
    totalPages: int
    totalElements: int
    page: int
    size: int


def _parse_csv_ints(value: str | None) -> list[int]:
    if not value:
        return []
    out: list[int] = []
    for chunk in value.split(","):
        token = chunk.strip()
        if token.isdigit():
            out.append(int(token))
    return out


def _parse_csv_strs(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def _time_filters_for_period(
    period: DashboardPeriod,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list:
    """IST calendar boundaries. For custom_range, from_date (inclusive 00:00 IST)
    and to_date (inclusive 23:59:59 IST) are used. If only one bound is supplied,
    the other is open-ended.
    """
    now = datetime.now(IST)
    if period == "all_time":
        return []
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [Order.created_at >= start]
    if period == "yesterday":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        return [Order.created_at >= yesterday_start, Order.created_at < today_start]
    if period == "last_week":
        start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [Order.created_at >= start]
    if period == "custom_range":
        filters = []
        if from_date:
            start_dt = datetime(from_date.year, from_date.month, from_date.day, 0, 0, 0, tzinfo=IST)
            filters.append(Order.created_at >= start_dt)
        if to_date:
            end_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, 999999, tzinfo=IST)
            filters.append(Order.created_at <= end_dt)
        return filters
    raise ValueError(f"Unknown period: {period}")


async def _store_details_for_rows(db: AsyncSession, stores: list[Store]) -> list[StoreDetailResponse]:
    if not stores:
        return []

    store_ids = [s.id for s in stores]

    petpooja_store_ids = set(
        (
            await db.execute(
                select(StorePetpoojaCredentials.store_id).where(
                    StorePetpoojaCredentials.store_id.in_(store_ids)
                )
            )
        ).scalars().all()
    )

    phonepe_store_ids = set(
        (
            await db.execute(
                select(StorePhonePeCredentials.store_id).where(
                    StorePhonePeCredentials.store_id.in_(store_ids)
                )
            )
        ).scalars().all()
    )

    pinelabs_store_ids = set(
        (
            await db.execute(
                select(StorePinelabsCredentials.store_id).where(
                    StorePinelabsCredentials.store_id.in_(store_ids)
                )
            )
        ).scalars().all()
    )

    t_stmt = (
        select(KioskTerminal)
        .where(KioskTerminal.store_id.in_(store_ids))
        .order_by(KioskTerminal.store_id, KioskTerminal.id)
    )
    terminals_all = (await db.execute(t_stmt)).scalars().all()
    terminals_by_store: defaultdict[int, list] = defaultdict(list)
    for t in terminals_all:
        terminals_by_store[t.store_id].append(t)

    return [
        StoreDetailResponse(
            store_id=s.id,
            store_code=s.store_code,
            store_name=s.store_name,
            is_active=bool(s.is_active),
            petpooja_configured=s.id in petpooja_store_ids,
            phonepe_configured=s.id in phonepe_store_ids,
            pinelabs_configured=s.id in pinelabs_store_ids,
            terminals=[
                KioskTerminalItem.model_validate(term)
                for term in terminals_by_store[s.id]
            ],
        )
        for s in stores
    ]


@router.get("/stores", response_model=List[StoreDetailResponse])
async def get_all_stores(
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(True, description="Return only active stores when true"),
):
    """Get all stores with terminal + provider-configuration flags for frontend discovery."""
    stmt = select(Store).order_by(Store.id)
    if active_only:
        stmt = stmt.where(Store.is_active.is_(True))
    stores = (await db.execute(stmt)).scalars().all()
    return await _store_details_for_rows(db, stores)


@router.get("/stores/{store_ref}", response_model=StoreDetailResponse)
async def get_store_details(
    store_ref: str,
    db: AsyncSession = Depends(get_db),
):
    """Get one store by numeric id or store_code (case-insensitive)."""
    stmt = select(Store).where(Store.store_code.ilike(store_ref))
    if store_ref.isdigit():
        stmt = stmt.where((Store.store_code.ilike(store_ref)) | (Store.id == int(store_ref)))
    store = (await db.execute(stmt)).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail=f"Store '{store_ref}' not found")
    details = await _store_details_for_rows(db, [store])
    return details[0]


@router.get("/analytics/summary", response_model=MultiStoreAnalyticsResponse)
async def get_multi_store_analytics(
    db: AsyncSession = Depends(get_db),
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    active_only: bool = Query(True, description="Include only active stores when true"),
):
    """
    Owner view analytics across all stores with combined totals and per-store breakdown.
    Uses completed orders only.
    """
    store_stmt = select(Store).order_by(Store.id)
    if active_only:
        store_stmt = store_stmt.where(Store.is_active.is_(True))
    stores = (await db.execute(store_stmt)).scalars().all()
    if not stores:
        return MultiStoreAnalyticsResponse(
            period=period,
            from_date=from_date,
            to_date=to_date,
            totalRevenue=0.0,
            totalOrders=0,
            dineInOrders=0,
            takeAwayOrders=0,
            upiRupees=0.0,
            cardRupees=0.0,
            cashRupees=0.0,
            stores=[],
        )

    store_ids = [s.id for s in stores]
    store_map = {s.id: s for s in stores}
    amt = Order.total_amount_include_tax
    filters = [
        Order.store_id.in_(store_ids),
        Order.payment_status == PaymentStatus.COMPLETED,
        *_time_filters_for_period(period, from_date, to_date),
    ]

    grouped_stmt = (
        select(
            Order.store_id,
            func.coalesce(func.sum(amt), 0),
            func.count(Order.id),
            func.coalesce(func.sum(case((Order.order_type == OrderType.DINEIN, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.order_type == OrderType.TAKEAWAY, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.payment_method == PaymentMethod.QR, amt), else_=0)), 0),
            func.coalesce(func.sum(case((Order.payment_method == PaymentMethod.CARD, amt), else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Order.payment_method.in_((PaymentMethod.CASH, PaymentMethod.MANUAL)),
                            amt,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(*filters)
        .group_by(Order.store_id)
    )
    rows = (await db.execute(grouped_stmt)).all()

    by_store: dict[int, StoreAnalyticsItem] = {}
    for row in rows:
        (
            sid,
            total_revenue,
            total_orders,
            dine_in,
            take_away,
            upi,
            card,
            cash,
        ) = row
        s = store_map.get(int(sid))
        if not s:
            continue
        by_store[int(sid)] = StoreAnalyticsItem(
            store_id=s.id,
            store_code=s.store_code,
            store_name=s.store_name,
            totalRevenue=float(total_revenue or 0),
            totalOrders=int(total_orders or 0),
            dineInOrders=int(dine_in or 0),
            takeAwayOrders=int(take_away or 0),
            upiRupees=float(upi or 0),
            cardRupees=float(card or 0),
            cashRupees=float(cash or 0),
        )

    store_items: list[StoreAnalyticsItem] = []
    for s in stores:
        store_items.append(
            by_store.get(
                s.id,
                StoreAnalyticsItem(
                    store_id=s.id,
                    store_code=s.store_code,
                    store_name=s.store_name,
                    totalRevenue=0.0,
                    totalOrders=0,
                    dineInOrders=0,
                    takeAwayOrders=0,
                    upiRupees=0.0,
                    cardRupees=0.0,
                    cashRupees=0.0,
                ),
            )
        )

    return MultiStoreAnalyticsResponse(
        period=period,
        from_date=from_date,
        to_date=to_date,
        totalRevenue=round(sum(s.totalRevenue for s in store_items), 2),
        totalOrders=sum(s.totalOrders for s in store_items),
        dineInOrders=sum(s.dineInOrders for s in store_items),
        takeAwayOrders=sum(s.takeAwayOrders for s in store_items),
        upiRupees=round(sum(s.upiRupees for s in store_items), 2),
        cardRupees=round(sum(s.cardRupees for s in store_items), 2),
        cashRupees=round(sum(s.cashRupees for s in store_items), 2),
        stores=store_items,
    )


@router.get("/transactions", response_model=AdminTransactionsResponse)
async def get_admin_transactions(
    db: AsyncSession = Depends(get_db),
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=200),
    sortBy: str = Query("created_at", pattern="^(created_at|amount|order_id)$"),
    sortDir: str = Query("desc", pattern="^(asc|desc)$"),
    period: DashboardPeriod = Query("all_time"),
    from_date: Optional[date] = Query(None, description="Start date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD."),
    to_date: Optional[date] = Query(None, description="End date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD."),
    start_at: datetime | None = Query(None, description="Optional UTC/ISO start datetime"),
    end_at: datetime | None = Query(None, description="Optional UTC/ISO end datetime"),
    active_only: bool = Query(True),
    store_ids: str | None = Query(None, description="CSV list, e.g. 1,2"),
    store_codes: str | None = Query(None, description="CSV list, e.g. KTRBANDRA,KTRVERSOVA"),
    order_type: OrderType | None = Query(None),
    payment_status: PaymentStatus | None = Query(None),
    payment_method: PaymentMethod | None = Query(None),
    kds_status: KdsStatus | None = Query(None),
    channel: str | None = Query(None),
    terminal_id: str | None = Query(None),
    search: str | None = Query(None, description="Search in order_id, kot_code"),
    min_amount: float | None = Query(None, ge=0),
    max_amount: float | None = Query(None, ge=0),
):
    """
    Owner transactions endpoint across all stores with filters for store/order/payment/KDS/date.
    """
    stmt = (
        select(
            Order.order_id,
            Order.store_id,
            Store.store_code,
            Store.store_name,
            Order.created_at,
            Order.order_type,
            Order.payment_method,
            Order.payment_status,
            Order.kds_status,
            Order.total_amount_include_tax,
            Order.channel,
            Order.terminal_id,
            Order.kot_code,
        )
        .join(Store, Store.id == Order.store_id)
    )

    filters = []
    if active_only:
        filters.append(Store.is_active.is_(True))

    for cond in _time_filters_for_period(period, from_date, to_date):
        filters.append(cond)
    if start_at:
        filters.append(Order.created_at >= start_at)
    if end_at:
        filters.append(Order.created_at <= end_at)

    ids = _parse_csv_ints(store_ids)
    if ids:
        filters.append(Order.store_id.in_(ids))
    codes = _parse_csv_strs(store_codes)
    if codes:
        filters.append(func.lower(Store.store_code).in_([c.lower() for c in codes]))

    if order_type:
        filters.append(Order.order_type == order_type)
    if payment_status:
        filters.append(Order.payment_status == payment_status)
    if payment_method:
        filters.append(Order.payment_method == payment_method)
    if kds_status:
        filters.append(Order.kds_status == kds_status)
    if channel:
        filters.append(Order.channel.ilike(f"%{channel}%"))
    if terminal_id:
        filters.append(Order.terminal_id == terminal_id)
    if min_amount is not None:
        filters.append(Order.total_amount_include_tax >= min_amount)
    if max_amount is not None:
        filters.append(Order.total_amount_include_tax <= max_amount)
    if search:
        search_term = f"%{search}%"
        filters.append(
            (Order.order_id.ilike(search_term)) | (Order.kot_code.ilike(search_term))
        )

    if filters:
        stmt = stmt.where(*filters)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_elements = (await db.execute(count_stmt)).scalar() or 0
    total_pages = (total_elements + size - 1) // size if total_elements else 0

    sort_map = {
        "created_at": Order.created_at,
        "amount": Order.total_amount_include_tax,
        "order_id": Order.order_id,
    }
    sort_col = sort_map.get(sortBy, Order.created_at)
    stmt = stmt.order_by(asc(sort_col) if sortDir == "asc" else desc(sort_col))
    stmt = stmt.offset(page * size).limit(size)

    rows = (await db.execute(stmt)).all()
    content = [
        AdminTransactionItem(
            orderId=r.order_id,
            store_id=r.store_id,
            store_code=r.store_code,
            store_name=r.store_name,
            createdAt=r.created_at,
            orderType=r.order_type,
            paymentMethod=r.payment_method,
            paymentStatus=r.payment_status,
            kdsStatus=r.kds_status,
            amount=float(r.total_amount_include_tax or 0),
            channel=r.channel,
            terminalId=r.terminal_id,
            kotCode=r.kot_code,
        )
        for r in rows
    ]

    return AdminTransactionsResponse(
        content=content,
        totalPages=total_pages,
        totalElements=int(total_elements),
        page=page,
        size=size,
    )


@router.get("/analytics/store-insights", response_model=OwnerInsightsResponse)
async def get_store_owner_insights(
    db: AsyncSession = Depends(get_db),
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    active_only: bool = Query(True),
    store_ids: str | None = Query(None, description="CSV list, e.g. 1,2"),
    store_codes: str | None = Query(None, description="CSV list, e.g. KTRBANDRA,KTRVERSOVA"),
    top_n: int = Query(5, ge=1, le=20),
):
    """
    Basic owner decision analytics by store, including top ordered items.
    Completed orders only.
    """
    store_stmt = select(Store).order_by(Store.id)
    if active_only:
        store_stmt = store_stmt.where(Store.is_active.is_(True))

    ids = _parse_csv_ints(store_ids)
    if ids:
        store_stmt = store_stmt.where(Store.id.in_(ids))
    codes = _parse_csv_strs(store_codes)
    if codes:
        store_stmt = store_stmt.where(func.lower(Store.store_code).in_([c.lower() for c in codes]))

    stores = (await db.execute(store_stmt)).scalars().all()
    if not stores:
        return OwnerInsightsResponse(
            period=period,
            from_date=from_date,
            to_date=to_date,
            totalRevenue=0.0,
            totalOrders=0,
            averageOrderValue=0.0,
            stores=[],
        )

    store_map = {s.id: s for s in stores}
    selected_store_ids = [s.id for s in stores]
    amt = Order.total_amount_include_tax
    filters = [
        Order.store_id.in_(selected_store_ids),
        Order.payment_status == PaymentStatus.COMPLETED,
        *_time_filters_for_period(period, from_date, to_date),
    ]

    summary_stmt = (
        select(
            Order.store_id,
            func.coalesce(func.sum(amt), 0),
            func.count(Order.id),
            func.coalesce(func.sum(case((Order.order_type == OrderType.DINEIN, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.order_type == OrderType.TAKEAWAY, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.payment_method == PaymentMethod.QR, amt), else_=0)), 0),
            func.coalesce(func.sum(case((Order.payment_method == PaymentMethod.CARD, amt), else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Order.payment_method.in_((PaymentMethod.CASH, PaymentMethod.MANUAL)),
                            amt,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(*filters)
        .group_by(Order.store_id)
    )
    summary_rows = (await db.execute(summary_stmt)).all()

    top_items_stmt = (
        select(
            Order.store_id,
            OrderItem.item_name,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("qty"),
            func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0).label("rev"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(*filters)
        .group_by(Order.store_id, OrderItem.item_name)
        .order_by(Order.store_id, desc(func.sum(OrderItem.quantity)))
    )
    top_item_rows = (await db.execute(top_items_stmt)).all()
    top_items_by_store: dict[int, list[TopOrderedItem]] = defaultdict(list)
    for r in top_item_rows:
        sid = int(r.store_id)
        if len(top_items_by_store[sid]) >= top_n:
            continue
        top_items_by_store[sid].append(
            TopOrderedItem(
                itemName=r.item_name or "Item",
                quantity=int(r.qty or 0),
                revenue=float(r.rev or 0),
            )
        )

    top_channel_stmt = (
        select(
            Order.store_id,
            Order.channel,
            func.count(Order.id).label("cnt"),
        )
        .where(*filters)
        .group_by(Order.store_id, Order.channel)
        .order_by(Order.store_id, desc(func.count(Order.id)))
    )
    top_channel_rows = (await db.execute(top_channel_stmt)).all()
    top_channel_by_store: dict[int, str] = {}
    for r in top_channel_rows:
        sid = int(r.store_id)
        if sid not in top_channel_by_store:
            top_channel_by_store[sid] = r.channel

    per_store_summary: dict[int, tuple] = {}
    for r in summary_rows:
        per_store_summary[int(r[0])] = r

    store_insights: list[StoreOwnerInsight] = []
    for sid in selected_store_ids:
        s = store_map[sid]
        row = per_store_summary.get(sid)
        if row:
            _, total_revenue, total_orders, dine_in, take_away, upi, card, cash = row
        else:
            total_revenue = total_orders = dine_in = take_away = upi = card = cash = 0

        total_orders_int = int(total_orders or 0)
        total_revenue_f = float(total_revenue or 0)
        store_insights.append(
            StoreOwnerInsight(
                store_id=s.id,
                store_code=s.store_code,
                store_name=s.store_name,
                totalRevenue=total_revenue_f,
                totalOrders=total_orders_int,
                averageOrderValue=round(total_revenue_f / total_orders_int, 2) if total_orders_int else 0.0,
                dineInOrders=int(dine_in or 0),
                takeAwayOrders=int(take_away or 0),
                upiRupees=float(upi or 0),
                cardRupees=float(card or 0),
                cashRupees=float(cash or 0),
                topItems=top_items_by_store.get(s.id, []),
                topChannel=top_channel_by_store.get(s.id),
            )
        )

    total_revenue_all = round(sum(s.totalRevenue for s in store_insights), 2)
    total_orders_all = sum(s.totalOrders for s in store_insights)
    return OwnerInsightsResponse(
        period=period,
        from_date=from_date,
        to_date=to_date,
        totalRevenue=total_revenue_all,
        totalOrders=total_orders_all,
        averageOrderValue=round(total_revenue_all / total_orders_all, 2) if total_orders_all else 0.0,
        stores=store_insights,
    )


@router.get("/accounting/settlement", response_model=AccountingSettlementResponse)
async def get_accounting_settlement(
    db: AsyncSession = Depends(get_db),
    period: DashboardPeriod = Query(
        "today",
        description="IST window: today, yesterday, last_week, all_time, or custom_range.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Start date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    to_date: Optional[date] = Query(
        None,
        description="End date (IST, inclusive). Required when period=custom_range. Format: YYYY-MM-DD.",
    ),
    active_only: bool = Query(True),
    store_ids: str | None = Query(None, description="CSV list, e.g. 1,2"),
    store_codes: str | None = Query(None, description="CSV list, e.g. KTRBANDRA,KTRVERSOVA"),
):
    """
    Detailed financial breakdown for reconciliation by store.
    Includes Net vs Gross sales, tax collected, and payment gateway/staff cash splits.
    Completed orders only.
    """
    store_stmt = select(Store).order_by(Store.id)
    if active_only:
        store_stmt = store_stmt.where(Store.is_active.is_(True))

    ids = _parse_csv_ints(store_ids)
    if ids:
        store_stmt = store_stmt.where(Store.id.in_(ids))
    codes = _parse_csv_strs(store_codes)
    if codes:
        store_stmt = store_stmt.where(func.lower(Store.store_code).in_([c.lower() for c in codes]))

    stores = (await db.execute(store_stmt)).scalars().all()
    if not stores:
        return AccountingSettlementResponse(period=period, from_date=from_date, to_date=to_date, stores=[])

    selected_store_ids = [s.id for s in stores]
    
    filters = [
        Order.store_id.in_(selected_store_ids),
        Order.payment_status == PaymentStatus.COMPLETED,
        *_time_filters_for_period(period, from_date, to_date),
    ]

    # Gross, Net, Takeaway, Payment types
    amt_inc = Order.total_amount_include_tax
    amt_exc = Order.total_amount_exclude_tax
    tw_inc = Order.takeaway_charges_include_tax

    summary_stmt = (
        select(
            Order.store_id,
            func.coalesce(func.sum(amt_inc), 0).label("gross"),
            func.coalesce(func.sum(amt_exc), 0).label("net"),
            func.coalesce(func.sum(tw_inc), 0).label("takeaway"),
            func.coalesce(func.sum(case((Order.payment_method == PaymentMethod.QR, amt_inc), else_=0)), 0).label("upi"),
            func.coalesce(func.sum(case((Order.payment_method == PaymentMethod.CARD, amt_inc), else_=0)), 0).label("card"),
            func.coalesce(
                func.sum(case((Order.payment_method.in_((PaymentMethod.CASH, PaymentMethod.MANUAL)), amt_inc), else_=0)), 0
            ).label("cash"),
        )
        .where(*filters)
        .group_by(Order.store_id)
    )
    summary_rows = (await db.execute(summary_stmt)).all()
    summary_by_store = {r.store_id: r for r in summary_rows}

    # PineLabs breakdown (CARD payments by terminal)
    card_filters = filters + [Order.payment_method == PaymentMethod.CARD]
    pinelabs_stmt = (
        select(
            Order.store_id,
            func.coalesce(Order.terminal_id, "Unknown").label("term_id"),
            func.coalesce(func.sum(amt_inc), 0).label("amt"),
            func.count(Order.id).label("cnt"),
        )
        .where(*card_filters)
        .group_by(Order.store_id, Order.terminal_id)
    )
    pinelabs_rows = (await db.execute(pinelabs_stmt)).all()
    
    pinelabs_by_store: dict[int, list[TerminalSettlement]] = defaultdict(list)
    for r in pinelabs_rows:
        pinelabs_by_store[int(r.store_id)].append(
            TerminalSettlement(
                terminalId=str(r.term_id),
                cardAmount=float(r.amt),
                cardTxnCount=int(r.cnt),
            )
        )

    # Cash breakdown (CASH payments by staff)
    cash_filters = filters + [Order.payment_method.in_((PaymentMethod.CASH, PaymentMethod.MANUAL))]
    cash_stmt = (
        select(
            Order.store_id,
            func.coalesce(Order.cash_collected_by_staff_name, "Unknown/Manual").label("staff_name"),
            func.coalesce(func.sum(amt_inc), 0).label("amt"),
            func.count(Order.id).label("cnt"),
        )
        .where(*cash_filters)
        .group_by(Order.store_id, Order.cash_collected_by_staff_name)
    )
    cash_rows = (await db.execute(cash_stmt)).all()

    cash_by_store: dict[int, list[StaffCashSettlement]] = defaultdict(list)
    for r in cash_rows:
        cash_by_store[int(r.store_id)].append(
            StaffCashSettlement(
                staffName=str(r.staff_name),
                cashAmount=float(r.amt),
                cashTxnCount=int(r.cnt),
            )
        )

    store_settlements: list[AccountingSettlementStore] = []
    for s in stores:
        r = summary_by_store.get(s.id)
        if r:
            gross = float(r.gross)
            net = float(r.net)
            takeaway = float(r.takeaway)
            upi = float(r.upi)
            card = float(r.card)
            cash = float(r.cash)
        else:
            gross = net = takeaway = upi = card = cash = 0.0

        store_settlements.append(
            AccountingSettlementStore(
                store_id=s.id,
                store_code=s.store_code,
                grossSales=gross,
                netSales=net,
                totalTax=round(gross - net, 2),
                takeawayChargesCollected=takeaway,
                totalUpi=upi,
                totalCard=card,
                totalCash=cash,
                pineLabsSettlement=pinelabs_by_store.get(s.id, []),
                cashSettlement=cash_by_store.get(s.id, []),
            )
        )

    return AccountingSettlementResponse(
        period=period,
        from_date=from_date,
        to_date=to_date,
        stores=store_settlements,
    )

@router.get("/kiosk-config", response_model=List[KioskConfigResponse])
async def get_kiosk_config(db: AsyncSession = Depends(get_db)):
    """
    **All active stores** — metadata and PineLabs `kiosk_terminals` per outlet.

    No `X-Store-Id` or query params: clients use this to discover `store_id`, store codes,
    and terminal ids for configuration.
    """
    stmt = select(Store).where(Store.is_active.is_(True)).order_by(Store.id)
    stores = (await db.execute(stmt)).scalars().all()
    if not stores:
        return []

    store_ids = [s.id for s in stores]

    pinelabs_store_ids = set(
        (
            await db.execute(
                select(StorePinelabsCredentials.store_id).where(
                    StorePinelabsCredentials.store_id.in_(store_ids)
                )
            )
        ).scalars().all()
    )

    t_stmt = (
        select(KioskTerminal)
        .where(KioskTerminal.store_id.in_(store_ids))
        .order_by(KioskTerminal.store_id, KioskTerminal.id)
    )
    terminals_all = (await db.execute(t_stmt)).scalars().all()
    terminals_by_store: defaultdict[int, list] = defaultdict(list)
    for t in terminals_all:
        terminals_by_store[t.store_id].append(t)

    return [
        KioskConfigResponse(
            store_id=s.id,
            store_code=s.store_code,
            store_name=s.store_name,
            pinelabs_configured=s.id in pinelabs_store_ids,
            terminals=[
                KioskTerminalItem.model_validate(term)
                for term in terminals_by_store[s.id]
            ],
        )
        for s in stores
    ]


class CashPinStaff(BaseModel):
    """Staff entries (PIN values are not returned; manage PINs via DB or a secure tool)."""
    id: int
    staff_name: str

    class Config:
        from_attributes = True


@router.get("/cash-pins", response_model=List[CashPinStaff])
async def list_cash_pins(
    db: AsyncSession = Depends(get_db),
    store: Store = Depends(get_store_context),
):
    """List registered cash-collection staff (id + name) for this store."""
    stmt = (
        select(CashPin)
        .where(CashPin.store_id == store.id)
        .order_by(CashPin.id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/cache/invalidate")
async def invalidate_store_caches(
    store: Store = Depends(get_store_context),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """Bust Redis cache for this store (credentials + meta)."""
    await invalidate_store_cache(redis_client, store.id)
    return {"status": "ok", "store_id": store.id}


@router.get("/logs")
async def get_app_logs(
    lines: int = Query(200, ge=1, le=2000),
    contains: str | None = Query(None, description="Optional case-insensitive line filter"),
):
    """
    Return recent lines from `app.log` for frontend diagnostics.
    """
    if not LOG_FILE_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    rows = await asyncio.to_thread(_tail_lines, LOG_FILE_PATH, lines)
    if contains:
        needle = contains.lower()
        rows = [line for line in rows if needle in line.lower()]

    return {
        "path": str(LOG_FILE_PATH.resolve()),
        "count": len(rows),
        "entries": [_parse_log_line(line) for line in rows],
    }


@router.get("/logs/stream")
async def stream_app_logs(
    request: Request,
    contains: str | None = Query(None, description="Optional case-insensitive line filter"),
    initial_lines: int = Query(50, ge=0, le=500),
):
    """
    SSE stream of `app.log` so frontend can watch logs in real-time.
    """
    if not LOG_FILE_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    async def event_gen():
        needle = contains.lower() if contains else None
        if initial_lines > 0:
            for line in await asyncio.to_thread(_tail_lines, LOG_FILE_PATH, initial_lines):
                if needle and needle not in line.lower():
                    continue
                yield f"data: {json.dumps({'type': 'log', 'entry': _parse_log_line(line)})}\n\n"

        with LOG_FILE_PATH.open("r", encoding="utf-8", errors="replace") as fp:
            fp.seek(0, os.SEEK_END)
            while True:
                if await request.is_disconnected():
                    break

                line = await asyncio.to_thread(fp.readline)
                if not line:
                    yield ": ping\n\n"
                    await asyncio.sleep(1.0)
                    continue

                value = line.rstrip("\n")
                if needle and needle not in value.lower():
                    continue
                yield f"data: {json.dumps({'type': 'log', 'entry': _parse_log_line(value)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
