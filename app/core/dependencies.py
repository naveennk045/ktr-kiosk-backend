from __future__ import annotations

import httpx
import redis.asyncio as redis
from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.store import Store
from app.db.session import get_db
from app.services.catalog_service import CatalogService
from app.services.order_service import OrderService
from app.services.store_cache import get_petpooja_credentials_cached
from app.utils.petpooja import PetpoojaClient

if TYPE_CHECKING:
    from app.services.payment_service import PaymentService


async def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def get_redis_client(request: Request) -> redis.Redis:
    if request.app.state.redis_client is None:
        raise HTTPException(status_code=503, detail="Redis connection not available")
    return request.app.state.redis_client


async def resolve_active_store(db: AsyncSession, raw: str) -> Store:
    """Resolve numeric id or store_code to an active Store."""
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="Store identifier is required (X-Store-Id or store_id)",
        )
    if raw.isdigit():
        sid = int(raw)
        stmt = select(Store).where(Store.id == sid, Store.is_active.is_(True))
    else:
        code = raw.upper()
        stmt = select(Store).where(Store.store_code == code, Store.is_active.is_(True))
    store = (await db.execute(stmt)).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found or inactive")
    return store


async def get_store_context(
    x_store_id: str = Header(
        ...,
        alias="X-Store-Id",
        description="Numeric store id or store_code (e.g. STORE-001)",
    ),
    db: AsyncSession = Depends(get_db),
) -> Store:
    return await resolve_active_store(db, x_store_id)


async def get_store_context_flexible(
    db: AsyncSession = Depends(get_db),
    x_store_id: str | None = Header(
        None,
        alias="X-Store-Id",
        description="Numeric store id or store_code",
    ),
    store_id: int | None = Query(
        None,
        description="Numeric store id when the client cannot send headers (e.g. browser EventSource)",
    ),
) -> Store:
    raw = (x_store_id or "").strip()
    if not raw and store_id is not None:
        raw = str(store_id)
    return await resolve_active_store(db, raw)


async def get_petpooja_client(
    http_client: httpx.AsyncClient = Depends(get_http_client),
    store: Store = Depends(get_store_context),
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncSession = Depends(get_db),
) -> PetpoojaClient:
    creds = await get_petpooja_credentials_cached(redis_client, db, store.id)
    if not creds:
        raise HTTPException(
            status_code=503,
            detail="Petpooja is not configured for this store",
        )
    return PetpoojaClient(http_client, creds)


async def get_catalog_service(
    redis_client=Depends(get_redis_client),
    petpooja_client: PetpoojaClient = Depends(get_petpooja_client),
    store: Store = Depends(get_store_context),
) -> CatalogService:
    return CatalogService(redis_client, petpooja_client, store.id)


async def get_order_service(
    db=Depends(get_db),
    catalog_service: CatalogService = Depends(get_catalog_service),
    petpooja_client: PetpoojaClient = Depends(get_petpooja_client),
    store: Store = Depends(get_store_context),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> OrderService:
    creds = await get_petpooja_credentials_cached(redis_client, db, store.id)
    if not creds:
        raise HTTPException(
            status_code=503,
            detail="Petpooja is not configured for this store",
        )
    return OrderService(db, catalog_service, petpooja_client, store, creds)


async def get_payment_service(
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> PaymentService:
    """Payment flows resolve store from the order row (no X-Store-Id on payment routes)."""
    from app.services.payment_service import PaymentService as PaymentServiceCls

    return PaymentServiceCls(db, http_client, redis_client)
