from fastapi import APIRouter, Depends
from app.db.schemas.payment import CashInitiateRequest, StatusResponse
from app.services.payment_service import PaymentService
from app.core.dependencies import get_payment_service
from app.db.models.order import KdsStatus

router = APIRouter()

@router.post("/init", response_model=StatusResponse)
async def initiate_cash_payment(
    request: CashInitiateRequest,
    service: PaymentService = Depends(get_payment_service)
):
    order = await service.initiate_cash(
        request.order_id,
        request.amount_paise,
        request.store_id,
        request.pin
    )

    return StatusResponse(
        order_id=order.order_id,
        payment_status=order.payment_status,
        provider_code=order.provider_code,
        provider_message="Cash Payment Recorded",
        provider_raw=order.provider_resp,
        kds_invoice_id=order.kds_invoice_id,
        kds_status=order.kds_status,
        kot_code=order.kot_code,
    )
