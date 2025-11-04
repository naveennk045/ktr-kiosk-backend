
from app.core.config import settings
from fastapi import APIRouter


router = APIRouter()


@router.get("/info")
def get_catalog():
    return {
        "app_name": settings.APP_NAME,
        "debug_mode": settings.DEBUG_MODE,
        "message": "This is the payment endpoint."
    }