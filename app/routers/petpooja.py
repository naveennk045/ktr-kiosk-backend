import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/callback")
async def petpooja_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Callback endpoint for Petpooja to push order status updates.
    """
    try:
        # Petpooja sends data as form-data or JSON?
        # Usually JSON, but sometimes form-data.
        # Let's try to parse both or just log the raw body first.

        body_bytes = await request.body()
        logger.info(f"Petpooja Callback Raw Body: {body_bytes.decode('utf-8')}")

        try:
            data = await request.json()
        except Exception:
             # Fallback if not JSON
             data = {}
             logger.warning("Petpooja Callback: Could not parse as JSON")

        logger.info(f"Petpooja Callback Parsed Data: {data}")

        # TODO: Implement status update logic here once schema is confirmed.
        # if "restID" in data and "orderID" in data:
        #    ...

        return {"status": "success", "message": "Callback received"}

    except Exception as e:
        logger.error(f"Error processing Petpooja callback: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
