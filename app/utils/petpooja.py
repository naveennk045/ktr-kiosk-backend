import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PetpoojaCredentials:
    app_key: str
    app_secret: str
    access_token: str
    restaurant_id: str
    fetch_menu_url: str
    create_order_url: str
    callback_url: str


class PetpoojaClient:
    def __init__(self, http_client: httpx.AsyncClient, creds: PetpoojaCredentials):
        self.client = http_client
        self.creds = creds
        self.app_key = creds.app_key
        self.app_secret = creds.app_secret
        self.access_token = creds.access_token
        self.restaurant_id = creds.restaurant_id

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "app-key": self.app_key,
            "app-secret": self.app_secret,
            "access-token": self.access_token,
        }

    async def fetch_menu(self) -> Dict[str, Any]:
        """
        Fetches the menu from Petpooja.
        """
        url = self.creds.fetch_menu_url
        payload = {"restID": self.restaurant_id}

        logger.info(f"Fetching Menu from Petpooja: {url}")

        for attempt in range(1, 4):
            try:
                response = await self.client.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                logger.info(f"Petpooja Fetch Menu Response (Attempt {attempt}): Success")

                success = data.get("success")
                if str(success) != "1":
                    msg = data.get("message") or data.get("errorMessage") or "Unknown error"
                    if "Timedout" in str(msg) or "timed out" in str(msg):
                        logger.warning(f"Petpooja API Timeout (Attempt {attempt}): {msg}")
                        if attempt < 3:
                            await asyncio.sleep(2 * attempt)
                            continue

                    logger.error(f"Petpooja Fetch Menu Failed: {msg}")
                    raise ValueError(f"Petpooja API Error: {msg}")

                return data

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Petpooja HTTP Error (Attempt {attempt}): {e.response.status_code} - {e.response.text}"
                )
                if attempt < 3:
                    await asyncio.sleep(2 * attempt)
                    continue
                raise
            except Exception as e:
                logger.error(f"Petpooja Fetch Menu Error (Attempt {attempt}): {e}", exc_info=True)
                if attempt < 3:
                    await asyncio.sleep(2 * attempt)
                    continue
                raise

        raise ValueError("Petpooja Fetch Menu Failed after 3 attempts")

    async def save_order(self, order_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Pushes an order to Petpooja."""
        url = self.creds.create_order_url

        payload_with_auth = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "access_token": self.access_token,
            **order_payload,
        }

        logger.info(f"Pushing Order to Petpooja: {url}")
        logger.info(payload_with_auth)

        try:
            response = await self.client.post(
                url,
                json=payload_with_auth,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Petpooja Save Order Response: {data}")

            if data.get("success") != "1":
                logger.error(f"Petpooja Save Order Failed: {data.get('message')}")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Petpooja Save Order HTTP Error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Petpooja Save Order Error: {e}", exc_info=True)
            raise
