import logging
import httpx
import redis.asyncio as redis
from sqlalchemy import select
from app.db.postgres import SessionLocal

from app.core.rista_utils import post_order_to_kds
from app.db.models.order import Order, PaymentStatus, KdsStatus

logger = logging.getLogger(__name__)


async def process_webhook_in_background(merchant_order_id: str, code: str, payload: dict,
                                        http_client: httpx.AsyncClient, redis_client: redis.Redis):
    logger.info(f"Background task started for order {merchant_order_id}...")
    async with SessionLocal() as db:
        async with db.begin():
            stmt = select(Order).where(Order.order_id == merchant_order_id)
            order = (await db.execute(stmt)).scalar_one_or_none()
            if not order:
                logger.error(f"Order {merchant_order_id} not found in BG task")
                return

            order.provider_code = code
            order.provider_resp = payload

            if code == "PAYMENT_SUCCESS":
                order.payment_status = PaymentStatus.COMPLETED

                # Post to KDS when payment is completed
                kdssuccess, invoice = await post_order_to_kds(order, http_client, redis_client)
                if kdssuccess and invoice:
                    order.kds_invoice_id = invoice
                # post_order_to_kds already updates kds_status & last_* fields
            elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED"):
                order.payment_status = PaymentStatus.FAILED
            else:
                order.payment_status = PaymentStatus.PENDING
