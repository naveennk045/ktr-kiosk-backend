
import asyncio
import logging
from app.db.session import SessionLocal
from app.services.order_service import OrderService
from app.services.catalog_service import CatalogService
from app.utils.petpooja import PetpoojaClient
from app.db.models.order import Order
from sqlalchemy import select
import httpx
import redis.asyncio as redis
from app.core.config import settings

# Configure logging to show up in console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting debug script...")

    # 1. Setup Resources
    http_client = httpx.AsyncClient()
    redis_client = redis.from_url(settings.REDIS_HOST, decode_responses=True)

    try:
        async with SessionLocal() as db:
            # 2. Initialize Services
            petpooja_client = PetpoojaClient(http_client)
            catalog_service = CatalogService(redis_client, petpooja_client)
            order_service = OrderService(db, catalog_service, petpooja_client)

            # 3. Fetch the most recent order
            stmt = select(Order).order_by(Order.created_at.desc()).limit(1)
            result = await db.execute(stmt)
            order = result.scalar_one_or_none()

            if not order:
                logger.error("No orders found in DB to test with.")
                return

            logger.info(f"Testing with Order ID: {order.order_id}, Status: {order.payment_status}, KDS: {order.kds_status}")

            # 4. Force Sync
            # We modify KDS status to NOT_POSTED to force a retry if it was already posted/failed
            # But sync_order_to_kds checks status internally, so we might need to reset it first if we want to force it.
            # actually sync_order_to_kds returns early if POSTED.

            # Resetting for test
            order.kds_status = "NOT_POSTED"

            logger.info("Syncing to Petpooja...")
            success, invoice_id = await order_service.sync_order_to_kds(order)

            logger.info(f"Sync Result: Success={success}, InvoiceID={invoice_id}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await http_client.aclose()
        await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())
