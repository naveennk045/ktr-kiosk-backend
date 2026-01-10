import logging
from fastapi import APIRouter
from . import edc, callback, dynamic_qr, cash

logger = logging.getLogger(__name__)
router = APIRouter()

router.include_router(dynamic_qr.router, prefix = "/qr", tags = ["Dynamic QR"])
router.include_router(edc.router, prefix="/edc", tags=["edc"])
router.include_router(cash.router, prefix="/cash", tags=["cash"])
router.include_router(callback.router, prefix="/webhook", tags=["payments"])
