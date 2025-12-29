import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.db.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.core.dependencies import get_order_service
from app.services.order_service import OrderService

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