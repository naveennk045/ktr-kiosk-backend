import json as _json
import logging
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db
from app.utils.petpooja import PetpoojaClient
from app.services.catalog_service import CatalogService

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/webhook/menu")
async def petpooja_menu_push(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook to receive Menu Push from Petpooja.
    PetPooja sends this as application/x-www-form-urlencoded
    with a 'restdata' key containing the menu JSON as a string.
    We also accept raw JSON for flexibility.
    """
    # ------------------------------------------------------------------ #
    # Step 1: Parse the incoming payload (form-encoded OR raw JSON)
    # ------------------------------------------------------------------ #
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "").lower()
    logger.info(f"Petpooja Menu Push — Content-Type: {content_type}")
    logger.info(f"Petpooja Menu Push — Raw body (first 500 chars): {raw_body[:500]}")

    data = None
    try:
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            # PetPooja typically sends: restdata=<url-encoded JSON string>
            form = await request.form()
            restdata = form.get("restdata") or form.get("RestData")
            if restdata:
                data = _json.loads(restdata)
                logger.info("Parsed menu from form field 'restdata'.")
            else:
                data = _json.loads(raw_body)
                logger.info("No 'restdata' field — decoded raw body as JSON.")
        else:
            data = _json.loads(raw_body)
            logger.info("Parsed menu from raw JSON body.")
    except Exception as parse_err:
        logger.error(f"Failed to parse menu push body: {parse_err}", exc_info=True)
        return {"success": "0", "message": f"Could not parse request body: {parse_err}"}

    if not data:
        logger.error("Parsed menu data is empty or None.")
        return {"success": "0", "message": "Empty payload received."}

    # ------------------------------------------------------------------ #
    # Step 2: Store raw data in DB
    # ------------------------------------------------------------------ #
    try:
        from app.db.models.menu import Menu
        new_menu = Menu(data=data, provider="petpooja")
        db.add(new_menu)
        await db.commit()
        await db.refresh(new_menu)
        logger.info(f"Menu stored in DB with ID: {new_menu.id}")
    except Exception as db_err:
        logger.error(f"Failed to store menu in DB: {db_err}", exc_info=True)
        return {"success": "0", "message": f"DB error: {db_err}"}

    # ------------------------------------------------------------------ #
    # Step 3: Clear ALL petpooja catalog cache keys, then rebuild cache
    # ------------------------------------------------------------------ #
    redis_client = request.app.state.redis_client
    if redis_client:
        # Explicit clear first
        try:
            keys = await redis_client.keys("petpooja_catalog_data_*")
            if keys:
                await redis_client.delete(*keys)
                logger.info(f"Cleared {len(keys)} Redis catalog cache key(s): {keys}")
            else:
                logger.info("No existing Redis catalog cache keys to clear.")
        except Exception as redis_err:
            logger.warning(f"Redis cache clear failed (non-fatal): {redis_err}", exc_info=True)

        # Rebuild cache from the new data
        http_client = request.app.state.http_client
        petpooja_client = PetpoojaClient(http_client)
        service = CatalogService(redis_client=redis_client, petpooja_client=petpooja_client)
        try:
            await service.process_and_cache_menu(data)
            logger.info("Menu processed and cached successfully (TTL=24h).")
        except Exception as cache_err:
            logger.error(f"Error rebuilding catalog cache: {cache_err}", exc_info=True)
    else:
        logger.warning("Redis client not available — skipping cache update.")

    return {"success": "1", "message": "Menu received and stored successfully."}


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
