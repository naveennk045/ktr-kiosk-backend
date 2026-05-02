import json as _json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Request, Depends
from sqlalchemy import or_, select
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


def _menu_payload_counts(data: Dict[str, Any]) -> Dict[str, int]:
    """Return lightweight menu section counts for observability logs."""
    return {
        "categories": len(data.get("categories") or []),
        "items": len(data.get("items") or []),
        "addongroups": len(data.get("addongroups") or []),
        "taxes": len(data.get("taxes") or []),
    }


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
    trace_id = request.headers.get("x-request-id") or str(uuid4())
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "").lower()
    logger.info(
        "[MenuWebhook][%s] Step 1/7 webhook received | content_type=%s | body_bytes=%s",
        trace_id,
        content_type,
        len(raw_body),
    )
    logger.debug(
        "[MenuWebhook][%s] Raw body preview (first 500 bytes): %s",
        trace_id,
        raw_body[:500],
    )

    data = None
    try:
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            restdata = form.get("restdata") or form.get("RestData")
            if restdata:
                data = _json.loads(restdata)
                logger.info(
                    "[MenuWebhook][%s] Step 2/7 payload parsed from form field 'restdata'",
                    trace_id,
                )
            else:
                data = _json.loads(raw_body)
                logger.info(
                    "[MenuWebhook][%s] Step 2/7 payload parsed from raw JSON body (no restdata form field)",
                    trace_id,
                )
        else:
            data = _json.loads(raw_body)
            logger.info(
                "[MenuWebhook][%s] Step 2/7 payload parsed from raw JSON body",
                trace_id,
            )
    except Exception as parse_err:
        logger.error(
            "[MenuWebhook][%s] parse failed: %s",
            trace_id,
            parse_err,
            exc_info=True,
        )
        return {"success": "0", "message": f"Could not parse request body: {parse_err}"}

    if not data:
        logger.error("[MenuWebhook][%s] parsed payload is empty", trace_id)
        return {"success": "0", "message": "Empty payload received."}

    counts = _menu_payload_counts(data)
    logger.info(
        "[MenuWebhook][%s] Step 3/7 payload validated | categories=%s | items=%s | addongroups=%s | taxes=%s",
        trace_id,
        counts["categories"],
        counts["items"],
        counts["addongroups"],
        counts["taxes"],
    )

    rest_id = _extract_petpooja_rest_id(data)
    if not rest_id:
        logger.error("[MenuWebhook][%s] Step 4/7 failed: restaurant id not found in payload", trace_id)
        return {
            "success": "0",
            "message": "Could not resolve Petpooja restaurant id from payload.",
        }
    logger.info("[MenuWebhook][%s] Step 4/7 restaurant resolved | rest_id=%s", trace_id, rest_id)

    stmt = select(StorePetpoojaCredentials).where(
        or_(
            StorePetpoojaCredentials.petpooja_restaurant_id == rest_id,
            StorePetpoojaCredentials.menu_sharing_code == rest_id,
        )
    )
    ppc = (await db.execute(stmt)).scalar_one_or_none()
    if not ppc:
        logger.error(
            "[MenuWebhook][%s] Step 5/7 failed: no store credentials found | rest_id=%s",
            trace_id,
            rest_id,
        )
        return {
            "success": "0",
            "message": f"No kiosk store configured for Petpooja restaurant id {rest_id}.",
        }
    logger.info(
        "[MenuWebhook][%s] Step 5/7 store mapping resolved | store_id=%s | credential_id=%s",
        trace_id,
        ppc.store_id,
        ppc.id,
    )

    try:
        logger.info("[MenuWebhook][%s] Step 6/7 writing menu row to database", trace_id)
        new_menu = Menu(store_id=ppc.store_id, data=data, provider="petpooja")
        db.add(new_menu)
        await db.commit()
        await db.refresh(new_menu)
        logger.info(
            "[MenuWebhook][%s] Step 6/7 database write complete | menu_id=%s | store_id=%s | provider=%s",
            trace_id,
            new_menu.id,
            ppc.store_id,
            new_menu.provider,
        )
    except Exception as db_err:
        logger.error(
            "[MenuWebhook][%s] database write failed: %s",
            trace_id,
            db_err,
            exc_info=True,
        )
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
                menu_sharing_code=ppc.menu_sharing_code,
                fetch_menu_url=ppc.fetch_menu_url,
                create_order_url=ppc.create_order_url,
                callback_url=ppc.callback_url,
            )
            petpooja_client = PetpoojaClient(http_client, creds)
            service = CatalogService(redis_client, petpooja_client, ppc.store_id)
            await service.process_and_cache_menu(data)
            logger.info("[MenuWebhook][%s] Step 7/7 cache rebuild complete (TTL=24h)", trace_id)
        except Exception as cache_err:
            logger.error(
                "[MenuWebhook][%s] cache rebuild failed: %s",
                trace_id,
                cache_err,
                exc_info=True,
            )
    else:
        logger.warning("[MenuWebhook][%s] redis unavailable; skipped cache rebuild", trace_id)

    logger.info("[MenuWebhook][%s] webhook flow complete", trace_id)
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
