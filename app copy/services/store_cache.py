"""
Redis cache-aside for store-scoped static data (metadata, integration credentials).
Invalidate with invalidate_store_cache() when credentials are updated (admin CRUD later).
"""
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.store import (
    Store,
    StorePetpoojaCredentials,
    StorePhonePeCredentials,
    StorePinelabsCredentials,
)
from app.utils.petpooja import PetpoojaCredentials

logger = logging.getLogger(__name__)

STORE_CACHE_TTL_SECONDS = 3600


def _key_meta(store_id: int) -> str:
    return f"store:{store_id}:meta"


def _key_petpooja(store_id: int) -> str:
    return f"store:{store_id}:petpooja"


def _key_phonepe(store_id: int) -> str:
    return f"store:{store_id}:phonepe"


def _key_pinelabs(store_id: int) -> str:
    return f"store:{store_id}:pinelabs"


async def invalidate_store_cache(redis_client: redis.Redis, store_id: int) -> None:
    """Delete all cached blobs for a store."""
    pattern = f"store:{store_id}:*"
    try:
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info("Invalidated %s store cache key(s) for store_id=%s", len(keys), store_id)
    except Exception as e:
        logger.warning("Store cache invalidation failed: %s", e, exc_info=True)


async def get_store_meta_cached(
    redis_client: redis.Redis,
    db: AsyncSession,
    store_id: int,
) -> Optional[dict[str, Any]]:
    key = _key_meta(store_id)
    try:
        raw = await redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning("Redis meta read failed: %s", e)

    row = await db.get(Store, store_id)
    if not row:
        return None
    payload = {
        "id": row.id,
        "store_code": row.store_code,
        "store_name": row.store_name,
        "is_active": row.is_active,
    }
    try:
        await redis_client.set(key, json.dumps(payload), ex=STORE_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Redis meta write failed: %s", e)
    return payload


async def get_petpooja_credentials_cached(
    redis_client: redis.Redis,
    db: AsyncSession,
    store_id: int,
) -> Optional[PetpoojaCredentials]:
    key = _key_petpooja(store_id)
    try:
        raw = await redis_client.get(key)
        if raw:
            d = json.loads(raw)
            return PetpoojaCredentials(
                app_key=d["app_key"],
                app_secret=d["app_secret"],
                access_token=d["access_token"],
                restaurant_id=d["restaurant_id"],
                menu_sharing_code=d.get("menu_sharing_code") or d["restaurant_id"],
                fetch_menu_url=d["fetch_menu_url"],
                create_order_url=d["create_order_url"],
                callback_url=d["callback_url"],
            )
    except Exception as e:
        logger.warning("Redis petpooja read failed: %s", e)

    stmt = select(StorePetpoojaCredentials).where(StorePetpoojaCredentials.store_id == store_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    creds = PetpoojaCredentials(
        app_key=row.app_key,
        app_secret=row.app_secret,
        access_token=row.access_token,
        restaurant_id=row.petpooja_restaurant_id,
        menu_sharing_code=row.menu_sharing_code,
        fetch_menu_url=row.fetch_menu_url,
        create_order_url=row.create_order_url,
        callback_url=row.callback_url,
    )
    blob = {
        "app_key": row.app_key,
        "app_secret": row.app_secret,
        "access_token": row.access_token,
        "restaurant_id": row.petpooja_restaurant_id,
        "menu_sharing_code": row.menu_sharing_code,
        "fetch_menu_url": row.fetch_menu_url,
        "create_order_url": row.create_order_url,
        "callback_url": row.callback_url,
    }
    try:
        await redis_client.set(key, json.dumps(blob), ex=STORE_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Redis petpooja write failed: %s", e)
    return creds


async def get_phonepe_row_cached(
    redis_client: redis.Redis,
    db: AsyncSession,
    store_id: int,
) -> Optional[StorePhonePeCredentials]:
    key = _key_phonepe(store_id)
    try:
        raw = await redis_client.get(key)
        if raw:
            d = json.loads(raw)
            row = StorePhonePeCredentials(
                store_id=store_id,
                merchant_id=d["merchant_id"],
                salt_key=d["salt_key"],
                salt_key_index=d["salt_key_index"],
                phonepe_store_id=d["phonepe_store_id"],
                terminal_id=d["terminal_id"],
                x_provider_id=d["x_provider_id"],
            )
            return row
    except Exception as e:
        logger.warning("Redis phonepe read failed: %s", e)

    stmt = select(StorePhonePeCredentials).where(StorePhonePeCredentials.store_id == store_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    blob = {
        "merchant_id": row.merchant_id,
        "salt_key": row.salt_key,
        "salt_key_index": row.salt_key_index,
        "phonepe_store_id": row.phonepe_store_id,
        "terminal_id": row.terminal_id,
        "x_provider_id": row.x_provider_id,
    }
    try:
        await redis_client.set(key, json.dumps(blob), ex=STORE_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Redis phonepe write failed: %s", e)
    return row


async def get_pinelabs_shared_cached(
    redis_client: redis.Redis,
    db: AsyncSession,
    store_id: int,
) -> Optional[StorePinelabsCredentials]:
    key = _key_pinelabs(store_id)
    try:
        raw = await redis_client.get(key)
        if raw:
            d = json.loads(raw)
            return StorePinelabsCredentials(
                store_id=store_id,
                base_url=d["base_url"],
                merchant_id=d["merchant_id"],
                user_id=d["user_id"],
                security_token=d["security_token"],
            )
    except Exception as e:
        logger.warning("Redis pinelabs read failed: %s", e)

    stmt = select(StorePinelabsCredentials).where(StorePinelabsCredentials.store_id == store_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    blob = {
        "base_url": row.base_url,
        "merchant_id": row.merchant_id,
        "user_id": row.user_id,
        "security_token": row.security_token,
    }
    try:
        await redis_client.set(key, json.dumps(blob), ex=STORE_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Redis pinelabs write failed: %s", e)
    return row
