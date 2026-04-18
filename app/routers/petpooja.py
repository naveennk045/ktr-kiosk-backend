import json as _json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.db.models.menu import Menu
from app.db.models.store import StorePetpoojaCredentials
from app.services.catalog_service import CatalogService
from app.utils.petpooja import PetpoojaClient, PetpoojaCredentials

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_petpooja_rest_id(data: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of Petpooja restaurant id from menu JSON."""
    if not isinstance(data, dict):
        return None
    for key in ("restID", "restId", "restaurantid", "restaurant_id"):
        v = data.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    restaurants = data.get("restaurants") or data.get("Restaurants")
    if isinstance(restaurants, list) and restaurants:
        r0 = restaurants[0]
        if isinstance(r0, dict):
            for key in ("restID", "restaurantid", "restaurant_id", "restId"):
                v = r0.get(key)
                if v is not None and str(v).strip():
                    return str(v).strip()
    return None


@router.post("/webhook/menu")
async def petpooja_menu_push(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook to receive Menu Push from Petpooja.
    PetPooja sends this as application/x-www-form-urlencoded
    with a 'restdata' key containing the menu JSON as a string.
    We also accept raw JSON for flexibility.
    """
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "").lower()
    logger.info(f"Petpooja Menu Push — Content-Type: {content_type}")
    logger.info(f"Petpooja Menu Push — Raw body (first 500 chars): {raw_body[:500]}")

    data = None
    try:
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
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

    rest_id = _extract_petpooja_rest_id(data)
    if not rest_id:
        return {
            "success": "0",
            "message": "Could not resolve Petpooja restaurant id from payload.",
        }

    stmt = select(StorePetpoojaCredentials).where(
        StorePetpoojaCredentials.petpooja_restaurant_id == rest_id
    )
    ppc = (await db.execute(stmt)).scalar_one_or_none()
    if not ppc:
        return {
            "success": "0",
            "message": f"No kiosk store configured for Petpooja restaurant id {rest_id}.",
        }

    try:
        new_menu = Menu(store_id=ppc.store_id, data=data, provider="petpooja")
        db.add(new_menu)
        await db.commit()
        await db.refresh(new_menu)
        logger.info(f"Menu stored in DB with ID: {new_menu.id} (store {ppc.store_id})")
    except Exception as db_err:
        logger.error(f"Failed to store menu in DB: {db_err}", exc_info=True)
        return {"success": "0", "message": f"DB error: {db_err}"}

    redis_client = request.app.state.redis_client
    if redis_client:
        try:
            http_client = request.app.state.http_client
            creds = PetpoojaCredentials(
                app_key=ppc.app_key,
                app_secret=ppc.app_secret,
                access_token=ppc.access_token,
                restaurant_id=ppc.petpooja_restaurant_id,
                fetch_menu_url=ppc.fetch_menu_url,
                create_order_url=ppc.create_order_url,
                callback_url=ppc.callback_url,
            )
            petpooja_client = PetpoojaClient(http_client, creds)
            service = CatalogService(redis_client, petpooja_client, ppc.store_id)
            await service.process_and_cache_menu(data)
            logger.info("Menu processed and cached successfully (TTL=24h).")
        except Exception as cache_err:
            logger.error(f"Error rebuilding catalog cache: {cache_err}", exc_info=True)
    else:
        logger.warning("Redis client not available — skipping cache update.")

    return {"success": "1", "message": "Menu received and stored successfully."}


@router.post("/callback")
async def petpooja_callback(request: Request):
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
