import httpx
import logging
from typing import Any, Dict, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class PetpoojaClient:
    def __init__(self, http_client: httpx.AsyncClient):
        self.client = http_client
        self.app_key = settings.PETPOOJA_API_KEY
        self.app_secret = settings.PETPOOJA_API_SECRET
        self.access_token = settings.PETPOOJA_ACCESS_TOKEN
        self.restaurant_id = settings.PETPOOJA_RESTAURANT_ID

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "app-key": self.app_key,
            "app-secret": self.app_secret,
            "access-token": self.access_token
        }

    async def fetch_menu(self) -> Dict[str, Any]:
        """
        Fetches the menu from Petpooja.
        URL: settings.PETPOOJA_FETCH_MENU_URL
        Payload: {"restID": "..."}
        """
        url = settings.PETPOOJA_FETCH_MENU_URL
        payload = {
            "restID": self.restaurant_id
        }

        logger.info(f"Fetching Menu from Petpooja: {url}")

        import asyncio
        for attempt in range(1, 4):  # Try 3 times
            try:
                response = await self.client.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                logger.info(f"Petpooja Fetch Menu Response (Attempt {attempt}): Success")

                # Check success (Allow string "1" or integer 1)
                success = data.get("success")
                if str(success) != "1":
                    msg = data.get('message') or data.get('errorMessage') or 'Unknown error'
                    # If it's a specific timeout error from sandbox, maybe we can retry?
                    if "Timedout" in str(msg) or "timed out" in str(msg):
                        logger.warning(f"Petpooja API Timeout (Attempt {attempt}): {msg}")
                        if attempt < 3:
                            await asyncio.sleep(2 * attempt) # Exponential backoff: 2s, 4s
                            continue

                    logger.error(f"Petpooja Fetch Menu Failed: {msg}")
                    raise ValueError(f"Petpooja API Error: {msg}")

                return data

            except httpx.HTTPStatusError as e:
                logger.error(f"Petpooja HTTP Error (Attempt {attempt}): {e.response.status_code} - {e.response.text}")
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
        """
        Pushes an order to Petpooja.
        URL: settings.PETPOOJA_CREATE_ORDER_URL
        """
        url = settings.PETPOOJA_CREATE_ORDER_URL

        # Inject auth credentials into the payload as per Petpooja docs/examples
        # The user example showed credentials in the body for saveOrder
        payload_with_auth = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "access_token": self.access_token,
            **order_payload
        }

        logger.info(f"Pushing Order to Petpooja: {url}")
        logger.debug(payload_with_auth)

        try:
            response = await self.client.post(
                url,
                json=payload_with_auth,
                # Headers might just need Content-Type since tokens are in body
                # But keeping consistent with Fetch Menu if needed, though 'saveOrder' usually takes them in body
                headers={"Content-Type": "application/json"},
                timeout=30.0
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
