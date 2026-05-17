import logging
from typing import Any, Dict

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.dependencies import get_db, get_redis_client, get_store_context
from app.db.models.store import Store
from app.db.models.menu import Menu

logger = logging.getLogger(__name__)

router = APIRouter()

class ItemDetailsPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: List[Dict[str, Any]]
    categories: List[Dict[str, Any]]

@router.get("/")
async def get_item_details(
    store: Store = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):

    menu_id = 1
    # if store.id == 2:
    #     menu_id = 38

    logger.info(f"Fetching default menu id={menu_id} for store {store.id}")

    result = await db.execute(select(Menu).filter(Menu.id == menu_id))
    default_menu = result.scalar_one_or_none()

    if default_menu and default_menu.data:
        return default_menu.data

    return {}


@router.post("/")
async def update_item_details(
    payload: ItemDetailsPayload,
    store: Store = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Add a new row with updated json_items data, setting provider to 'ktr-one'.
    Wipes the catalog cache for this store so the new menu is fetched.
    """
    # Fetch default menu to preserve taxes, addons, etc.
    menu_id = 1
    logger.info(f"Fetching default menu id={menu_id} for store {store.id} to merge updates")
    result = await db.execute(select(Menu).filter(Menu.id == menu_id))
    default_menu = result.scalar_one_or_none()

    merged_data = payload.model_dump()
    if default_menu and default_menu.data:
        merged_data = default_menu.data.copy()
        payload_dict = payload.model_dump()
        merged_data["categories"] = payload_dict["categories"]
        merged_data["items"] = payload_dict["items"]
    else:
        logger.warning(f"Default menu id={menu_id} not found, saving only items and categories.")

    new_menu = Menu(
        store_id=store.id,
        provider="ktr-one",
        data=merged_data
    )
    db.add(new_menu)
    await db.commit()
    await db.refresh(new_menu)
    
    logger.info(f"Added new 'ktr-one' menu row with id={new_menu.id} for store {store.id}")

    # Wipe catalog cache
    try:
        pattern = f"petpooja_catalog_data_{store.id}_*"
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info(f"Cleared {len(keys)} catalog cache key(s) for store {store.id}.")
        else:
            logger.info(f"No catalog cache found to clear for store {store.id}.")
    except Exception as e:
        logger.error(f"Error clearing cache keys: {e}", exc_info=True)

    return {"status": "success", "message": "Menu updated and cache cleared", "menu_id": new_menu.id}
