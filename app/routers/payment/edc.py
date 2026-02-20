from fastapi import APIRouter, Depends
from app.db.schemas.payment import EDCInitiateRequest, EDCInitiateResponse, EDCStatusResponse
from app.services.payment_service import PaymentService
from app.core.dependencies import get_payment_service

router = APIRouter()

@router.post("/init", response_model=EDCInitiateResponse)
async def initiate_edc(
        request: EDCInitiateRequest,
        service: PaymentService = Depends(get_payment_service)
):
    order = await service.initiate_edc(
        request.order_id,
        request.amount_paise,
        request.store_id
    )

    provider_msg = "Request sent to Pine Labs Terminal"
    if order.provider_resp:
        provider_msg = order.provider_resp.get("ResponseMessage", provider_msg)

    return EDCInitiateResponse(
        order_id=order.order_id,
        transaction_id=order.order_id,
        amount=request.amount_paise,
        message=provider_msg,
        provider="Pine Labs EDC"
    )

@router.get("/status/{order_id}", response_model=EDCStatusResponse)
async def check_edc_status(
        order_id: str,
        service: PaymentService = Depends(get_payment_service)
):
    order = await service.check_status(order_id)

    data = order.provider_resp or {}

    amt = data.get("Amount")
    if amt:
        try:
            amt = int(float(amt))
        except:
             amt = None

    return EDCStatusResponse(
        order_id=order.order_id,
        transaction_id=order.order_id,
        payment_status=order.payment_status,
        provider_code=order.provider_code,
        payment_mode=str(data.get("PaymentMode", "")),
        amount=amt,
        payment_state=str(data.get("ResponseCode", "")),
        reference_number=str(data.get("PlutusTransactionReferenceID", "")),
        provider_raw=data,
        kds_invoice_id=order.kds_invoice_id,
        kds_status=order.kds_status,
        kot_code=order.kot_code,
    )
