import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/webhook/menu")
async def petpooja_menu_push(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook to receive Menu Push from Petpooja.
    Stores raw JSON in DB and triggers processing.
    """
    try:
        data = await request.json()
        logger.info(f"Petpooja Menu Push Received")

        # 1. Store in DB
        from app.db.models.menu import Menu
        new_menu = Menu(data=data, provider="petpooja")
        db.add(new_menu)
        await db.commit()
        await db.refresh(new_menu)

        logger.info(f"Menu stored in DB with ID: {new_menu.id}")

        # 2. Trigger Processing
        redis_client = request.app.state.redis_client
        if redis_client:
            from app.services.catalog_service import CatalogService
            # We don't need petpooja client for processing data we already have
            service = CatalogService(redis_client=redis_client, petpooja_client=None)

            try:
                await service.process_and_cache_menu(data)
                logger.info("Menu processed and cached successfully.")
            except Exception as se:
                logger.error(f"Error processing menu in service: {se}", exc_info=True)
        else:
            logger.warning("Redis client not available in app state, skipping cache update.")

        return {"success": "1", "message": "Menu received and stored successfully."}

    except Exception as e:
        logger.error(f"Error processing Petpooja Menu Push: {e}", exc_info=True)
        return {"success": "0", "message": str(e)}

@router.post("/callback")
async def petpooja_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Callback endpoint for Petpooja to push order status updates.
    """
    try:
        body_bytes = await request.body()
        logger.info(f"Petpooja Callback Raw Body: {body_bytes.decode('utf-8')}")

        try:
            data = await request.json()
        except Exception:
            data = {}

        logger.info(f"Petpooja Callback Parsed Data: {data}")
        return {"status": "success", "message": "Callback received"}
    except Exception as e:
        logger.error(f"Error processing Petpooja callback: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
