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

    # Manual Mapping for EDC Response
    provider_msg = "Request sent to Terminal"
    if order.provider_resp:
        provider_msg = order.provider_resp.get("message", provider_msg)

    return EDCInitiateResponse(
        order_id=order.order_id,
        transaction_id=order.order_id,
        amount=request.amount_paise,
        message=provider_msg
    )

@router.get("/status/{order_id}", response_model=EDCStatusResponse)
async def check_edc_status(
        order_id: str,
        service: PaymentService = Depends(get_payment_service)
):
    order = await service.check_status(order_id)

    # Extract EDC specific fields from JSON
    raw = order.provider_resp or {}
    data = raw.get("data", {})

    return EDCStatusResponse(
        order_id=order.order_id,
        transaction_id=order.order_id,
        payment_status=order.payment_status,
        provider_code=order.provider_code,
        # EDC specific mappings
        payment_mode=data.get("paymentMode"),
        amount=data.get("amount"),
        payment_state=data.get("paymentState"),
        reference_number=data.get("referenceNumber"),

        provider_raw=raw,
        kds_invoice_id=order.kds_invoice_id,
        kds_status=order.kds_status,
        kot_code=order.kot_code,
    )
