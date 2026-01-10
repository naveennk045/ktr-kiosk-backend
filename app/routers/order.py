import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.db.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.core.dependencies import get_order_service, get_db
from app.services.order_service import OrderService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/", response_model=OrderCreateResponse)
async def create_order(
        request: OrderCreateRequest,
        service: OrderService = Depends(get_order_service),
):
    """
    Create a new order.
    Delegates complex logic (Tax calc, KOT generation, DB save) to OrderService.
    """
    try:
        new_order = await service.create_order(request)

        return OrderCreateResponse(
            order_id=new_order.order_id,
            amount_with_tax=new_order.total_amount_include_tax,
            amount_without_tax=new_order.total_amount_exclude_tax,
            kot_code=new_order.kot_code,
            order_type=new_order.order_type
        )

    except ValueError as e:
        # Catch validation errors (e.g. Invalid SKU)
        logger.warning(f"Order validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"System error creating order: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process order."
        )

# --- DASHBOARD ENDPOINTS ---

from app.services.dashboard_service import DashboardService
from app.db.schemas.dashboard import OrderGridResponse, OrderDetailResponse
from typing import Optional

async def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)

@router.get("/", response_model=OrderGridResponse)
async def get_orders(
    page: int = 0,
    size: int = 20,
    sortBy: str = "created_at",
    sortDir: str = "desc",
    status: Optional[str] = None,
    search: Optional[str] = None,
    service: DashboardService = Depends(get_dashboard_service)
):
    return await service.get_orders_grid(page, size, sortBy, sortDir, status, search)

@router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order_detail(
    order_id: str,
    service: DashboardService = Depends(get_dashboard_service)
):
    order = await service.get_order_detail(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
