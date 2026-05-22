import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.core.dependencies import get_discount_service, get_store_context_flexible
from app.db.models.store import Store
from app.db.schemas.discount import (
    DiscountCreate,
    DiscountUpdate,
    DiscountStatusUpdate,
    DiscountResponse,
    DiscountValidateRequest,
    DiscountValidateResponse
)
from app.services.discount_service import DiscountService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discounts", tags=["discounts"])

@router.get("", response_model=List[DiscountResponse])
async def list_discounts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    application_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    try:
        return await service.list_discounts(
            page=page,
            limit=limit,
            store_id=store.id,
            application_type=application_type,
            is_active=is_active,
            search=search
        )
    except Exception as e:
        logger.error(f"Error listing discounts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve discounts."
        )

@router.get("/eligible", response_model=List[DiscountResponse])
async def get_eligible_discounts(
    cart_amount: float = Query(0.0, ge=0),
    application_type: Optional[str] = None,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    try:
        return await service.get_eligible_discounts(
            application_type=application_type,
            store_id=store.id,
            cart_amount=cart_amount
        )
    except Exception as e:
        logger.error(f"Error fetching eligible discounts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve eligible discounts."
        )

@router.post("/validate", response_model=DiscountValidateResponse)
async def validate_discount(
    request: DiscountValidateRequest,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    try:
        res = await service.validate_discount(
            application_type=request.application_type,
            code=request.code,
            store_id=store.id,
            cart_amount=request.cart_amount
        )
        return DiscountValidateResponse(
            valid=res["valid"],
            discount_id=res.get("discount_id"),
            discount_type=res.get("discount_type"),
            discount_value=res.get("discount_value"),
            discount_amount=res.get("discount_amount"),
            message=res["message"]
        )
    except Exception as e:
        logger.error(f"Error validating discount: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not validate discount."
        )

@router.get("/{discount_id}", response_model=DiscountResponse)
async def get_discount(
    discount_id: int,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    discount = await service.get_discount(discount_id)
    if not discount or (discount.store_id is not None and discount.store_id != store.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found."
        )
    usage_count = await service.get_usage_count(discount_id)
    return DiscountResponse(
        id=discount.id,
        store_id=discount.store_id,
        name=discount.name,
        application_type=discount.application_type,
        code=discount.code,
        discount_type=discount.discount_type,
        value=float(discount.value) if discount.value is not None else None,
        max_discount_amount=float(discount.max_discount_amount) if discount.max_discount_amount is not None else None,
        min_order_amount=float(discount.min_order_amount) if discount.min_order_amount is not None else None,
        usage_limit=discount.usage_limit,
        start_date=discount.start_date,
        end_date=discount.end_date,
        is_active=discount.is_active,
        is_deleted=discount.is_deleted,
        created_at=discount.created_at,
        updated_at=discount.updated_at,
        usage_count=usage_count
    )

@router.post("", response_model=DiscountResponse, status_code=status.HTTP_201_CREATED)
async def create_discount(
    request: DiscountCreate,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    try:
        # Enforce store context from headers
        request.store_id = store.id
        
        # Check if code is already registered per store context
        if request.application_type.upper() == "COUPON" and request.code:
            existing = await service.get_discount_by_code(request.code, store.id)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Coupon code '{request.code}' is already active/exists in this store context."
                )

        new_discount = await service.create_discount(request)
        return DiscountResponse(
            id=new_discount.id,
            store_id=new_discount.store_id,
            name=new_discount.name,
            application_type=new_discount.application_type,
            code=new_discount.code,
            discount_type=new_discount.discount_type,
            value=float(new_discount.value) if new_discount.value is not None else None,
            max_discount_amount=float(new_discount.max_discount_amount) if new_discount.max_discount_amount is not None else None,
            min_order_amount=float(new_discount.min_order_amount) if new_discount.min_order_amount is not None else None,
            usage_limit=new_discount.usage_limit,
            start_date=new_discount.start_date,
            end_date=new_discount.end_date,
            is_active=new_discount.is_active,
            is_deleted=new_discount.is_deleted,
            created_at=new_discount.created_at,
            updated_at=new_discount.updated_at,
            usage_count=0
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating discount: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create discount."
        )

@router.put("/{discount_id}", response_model=DiscountResponse)
async def update_discount(
    discount_id: int,
    request: DiscountUpdate,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    curr = await service.get_discount(discount_id)
    if not curr or (curr.store_id is not None and curr.store_id != store.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found for this store."
        )

    # Enforce store context
    request.store_id = store.id

    if request.code:
        existing = await service.get_discount_by_code(request.code, store.id)
        if existing and existing.id != discount_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Coupon code '{request.code}' is already in use in this store context."
            )

    updated = await service.update_discount(discount_id, request)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found."
        )
    usage_count = await service.get_usage_count(discount_id)
    return DiscountResponse(
        id=updated.id,
        store_id=updated.store_id,
        name=updated.name,
        application_type=updated.application_type,
        code=updated.code,
        discount_type=updated.discount_type,
        value=float(updated.value) if updated.value is not None else None,
        max_discount_amount=float(updated.max_discount_amount) if updated.max_discount_amount is not None else None,
        min_order_amount=float(updated.min_order_amount) if updated.min_order_amount is not None else None,
        usage_limit=updated.usage_limit,
        start_date=updated.start_date,
        end_date=updated.end_date,
        is_active=updated.is_active,
        is_deleted=updated.is_deleted,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        usage_count=usage_count
    )

@router.patch("/{discount_id}/status", response_model=DiscountResponse)
async def update_discount_status(
    discount_id: int,
    request: DiscountStatusUpdate,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    curr = await service.get_discount(discount_id)
    if not curr or (curr.store_id is not None and curr.store_id != store.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found for this store."
        )

    updated = await service.update_discount_status(discount_id, request.is_active)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found."
        )
    usage_count = await service.get_usage_count(discount_id)
    return DiscountResponse(
        id=updated.id,
        store_id=updated.store_id,
        name=updated.name,
        application_type=updated.application_type,
        code=updated.code,
        discount_type=updated.discount_type,
        value=float(updated.value) if updated.value is not None else None,
        max_discount_amount=float(updated.max_discount_amount) if updated.max_discount_amount is not None else None,
        min_order_amount=float(updated.min_order_amount) if updated.min_order_amount is not None else None,
        usage_limit=updated.usage_limit,
        start_date=updated.start_date,
        end_date=updated.end_date,
        is_active=updated.is_active,
        is_deleted=updated.is_deleted,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        usage_count=usage_count
    )

@router.delete("/{discount_id}", status_code=status.HTTP_200_OK)
async def delete_discount(
    discount_id: int,
    store: Store = Depends(get_store_context_flexible),
    service: DiscountService = Depends(get_discount_service)
):
    curr = await service.get_discount(discount_id)
    if not curr or (curr.store_id is not None and curr.store_id != store.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found for this store."
        )

    success = await service.delete_discount(discount_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount with ID {discount_id} not found."
        )
    return {"status": "success", "message": "Discount deleted successfully."}
