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
    # Internal / menu-JSON identifier (webhook routing vs petpooja_restaurant_id).
    restaurant_id: str
    # Petpooja menu sharing code — sent as restID in fetch-menu and order payload.
    menu_sharing_code: str
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
        self.menu_sharing_code = creds.menu_sharing_code

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
        payload = {"restID": self.creds.menu_sharing_code}

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
        client_order_id = (
            order_payload.get("orderinfo", {})
            .get("OrderInfo", {})
            .get("Order", {})
            .get("details", {})
            .get("orderID")
        )

        payload_with_auth = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "access_token": self.access_token,
            **order_payload,
        }

        logger.info(
            "Petpooja save_order request started | url=%s | client_order_id=%s",
            url,
            client_order_id,
        )

        try:
            response = await self.client.post(
                url,
                json=payload_with_auth,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "Petpooja save_order response received | client_order_id=%s | success=%s | code=%s | message=%s",
                client_order_id,
                data.get("success"),
                data.get("code"),
                data.get("message"),
            )

            if data.get("success") != "1":
                logger.error(
                    "Petpooja save_order failed | client_order_id=%s | message=%s",
                    client_order_id,
                    data.get("message"),
                )

            return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "Petpooja save_order HTTP error | client_order_id=%s | status=%s",
                client_order_id,
                e.response.status_code,
            )
            raise
        except Exception as e:
            logger.error(
                "Petpooja save_order exception | client_order_id=%s | error=%s",
                client_order_id,
                e,
                exc_info=True,
            )
            raise
