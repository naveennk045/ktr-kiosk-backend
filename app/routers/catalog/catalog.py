import httpx
import redis.asyncio as redis
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
import time
import jwt

from app.core.config import settings
from app.core.dependencies import get_http_client, get_redis_client

logger = logging.getLogger(__name__)

router = APIRouter()


def generate_jwt_token():
    """
    Using the secret key and api-key we need to generate token.
    """
    token_creation_time = int(time.time())
    payload = {
        "iss": settings.PI_KEY,
        "iat": token_creation_time
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


@router.get("/")
async def get_catalog(
        channel: str,
        http_client: httpx.AsyncClient = Depends(get_http_client),
        redis_client: redis.Redis = Depends(get_redis_client)
):
    cache_key = f"{channel}_catalog_data"

    # 1. Check cache first
    try:
        if cached_data := await redis_client.get(cache_key):
            logger.info(f"Returning catalog for channel '{channel}' from cache.")
            return json.loads(cached_data)
    except Exception as e:
        logger.error(f"Cache read error for channel '{channel}': {e}", exc_info=True)

    # 2. Generate token in a threadpool
    try:
        token = await run_in_threadpool(generate_jwt_token)
    except Exception as e:
        logger.error(f"Failed to generate JWT: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process authentication."
        )

    headers = {
        "x-api-key": settings.PI_KEY,
        "x-api-token": token,
        "content-type": 'application/json'
    }
    params = {
        "branch": settings.BRANCH_CODE,
        "channel": channel
    }

    try:
        url = f"{settings.RISTA_BASE_URL}/catalog"
        logger.info(f"Fetching fresh catalog for channel '{channel}' from Rista API...")
        response = await http_client.get(url, headers=headers, params=params)
        response.raise_for_status()

        catalog_data = response.json()

        if catalog_data is None:
            logger.error(f"Rista API returned null data for channel '{channel}'.")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Invalid response structure from upstream API: received null data."
            )

        # 4. Store the catalog data in cache
        try:
            await redis_client.set(
                cache_key,
                json.dumps(catalog_data),
                ex=3600  # 1 hour expiration
            )
            logger.info(f"Successfully cached catalog for channel '{channel}'.")
        except Exception as e:
            logger.warning(f"Cache write error for channel '{channel}': {e}", exc_info=True)

        return catalog_data

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Rista API returned status {e.response.status_code} for channel '{channel}'. Response: {e.response.text}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error from upstream catalog API."
        )
    except httpx.RequestError as e:
        logger.error(f"Cannot connect to Rista API for channel '{channel}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot connect to upstream catalog API."
        )