import time
import jwt
import httpx
import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException
from app.core.config import settings

logger = logging.getLogger(__name__)

class RistaClient:
    def __init__(self, http_client: httpx.AsyncClient):
        self.client = http_client
        self.base_url = settings.RISTA_BASE_URL
        self.branch_code = settings.BRANCH_CODE

    def _generate_token(self, request_id: Optional[str] = None) -> str:
        now = int(time.time())
        payload = {"iss": settings.PI_KEY, "iat": now}
        if request_id: payload["jti"] = f"{request_id}_{now}"
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    def _get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        return {
            "x-api-key": settings.PI_KEY,
            "x-api-token": self._generate_token(request_id),
            "content-type": "application/json",
        }

    async def fetch_catalog_raw(self, channel: str) -> Dict[str, Any]:
        url = f"{self.base_url}/catalog"
        params = {"branch": self.branch_code, "channel": channel}
        response = await self.client.get(url, headers=self._get_headers(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    async def post_sale(self, sale_payload: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/sale"
        response = await self.client.post(url, headers=self._get_headers(request_id), json=sale_payload, timeout=30)
        response.raise_for_status()
        return response.json()

    async def get_sale_status(self, order_transaction_id: str) -> Optional[str]:
        url = f"{self.base_url}/sale"
        params = {"orderTransactionId": order_transaction_id}
        try:
            response = await self.client.get(url, headers=self._get_headers(), params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return data[0].get("invoiceNumber")
        except Exception:
            pass
        return None