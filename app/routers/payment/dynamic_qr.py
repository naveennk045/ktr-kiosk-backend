from fastapi import APIRouter, Depends
from app.db.schemas.payment import QRInitiateRequest, QRInitiateResponse, StatusResponse
from app.services.payment_service import PaymentService
from app.core.dependencies import get_payment_service

router = APIRouter()

@router.post("/init", response_model=QRInitiateResponse)
async def initiate_qr(
        request: QRInitiateRequest,
        service: PaymentService = Depends(get_payment_service)
):
    order = await service.initiate_qr(request.order_id, request.amount_paise, request.store_id)

    return QRInitiateResponse(
        order_id=order.order_id,
        transaction_id=order.provider_txn_id or order.order_id,
        qr_string=order.qr_string,
        expires_at=order.qr_expires_at
    )

@router.get("/status/{order_id}", response_model=StatusResponse)
async def check_qr_status(
        order_id: str,
        service: PaymentService = Depends(get_payment_service)
):
    order = await service.check_status(order_id)

    return StatusResponse(
        order_id=order.order_id,
        payment_status=order.payment_status,
        provider_code=order.provider_code,
        provider_raw=order.provider_resp,
        kds_invoice_id=order.kds_invoice_id,
        kds_status=order.kds_status,
        kot_code=order.kot_code,
    )
