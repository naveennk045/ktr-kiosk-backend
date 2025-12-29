import time
import jwt
import httpx
import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException, status
from app.core.config import settings

logger = logging.getLogger(__name__)

class RistaClient:
    def __init__(self, http_client: httpx.AsyncClient):
        self.client = http_client
        self.base_url = settings.RISTA_BASE_URL
        self.branch_code = settings.BRANCH_CODE

    def _generate_jwt_token(self, request_id: Optional[str] = None) -> str:
        token_creation_time = int(time.time())
        payload: Dict[str, Any] = {
            "iss": settings.PI_KEY,
            "iat": token_creation_time,
        }

        if request_id:
            payload["jti"] = f"{request_id}_{token_creation_time}"

        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    async def fetch_catalog_raw(self, channel: str) -> Dict[str, Any]:
        try:
            token = self._generate_jwt_token()
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not process authentication.",
            )

        headers = {
            "x-api-key": settings.PI_KEY,
            "x-api-token": token,
            "content-type": "application/json",
        }
        params = {"branch": self.branch_code, "channel": channel}

        try:
            url = f"{self.base_url}/catalog"
            response = await self.client.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            if data is None:
                raise HTTPException(
                    status_code=502, detail="Upstream API returned null data."
                )
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Rista API Error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error fetching catalog from upstream API.",
            )
        except Exception as e:
            logger.error(f"Network/Unknown error fetching catalog: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error connecting to Rista API.",
            )