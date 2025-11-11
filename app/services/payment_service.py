import logging
import httpx
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import SessionLocal
from app.db.models.order import Order, PaymentStatus
from app.core.rista_utils import post_order_to_kds  # Import your new KDS function

logger = logging.getLogger(__name__)


# noinspection PyTypeChecker
async def process_webhook_in_background(
        merchant_order_id: str,
        code: str,
        payload: dict,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis
):
    """
    This function runs in the background to process the payment confirmation.
    """
    logger.info(f"Background task started for order {merchant_order_id}...")

    db: AsyncSession
    async with SessionLocal() as db:
        try:
            async with db.begin():
                # Lock the order row
                stmt = select(Order).where(
                    Order.order_id == merchant_order_id
                ).with_for_update()

                result = await db.execute(stmt)
                order = result.scalar_one_or_none()

                if not order:
                    logger.error(f"[BG] Order {merchant_order_id} not found.")
                    return
                if order.payment_status == PaymentStatus.COMPLETED:
                    logger.info(f"[BG] Order {merchant_order_id} already completed. Skipping.")
                    return

                # Update the order
                order.provider_code = code
                order.provider_resp = payload

                if code == "PAYMENT_SUCCESS":
                    logger.info(f"[BG] Payment success for {merchant_order_id}. Updating DB...")
                    order.payment_status = PaymentStatus.COMPLETED

                    # Post to KDS
                    kds_success, invoice_id = await post_order_to_kds(order, http_client, redis_client)

                    if kds_success:
                        if invoice_id:
                            logger.info(f"[BG] KDS Invoice ID for {merchant_order_id}: {invoice_id}")
                            order.kds_invoice_id = invoice_id
                        else:
                            logger.warning(f"[BG] KDS post for {merchant_order_id} was 409 or had no invoice ID.")
                    else:
                        logger.error(f"[BG] CRITICAL: Order {merchant_order_id} PAID but FAILED to post to KDS.")

                elif code in ("PAYMENT_PENDING", "PENDING"):
                    order.payment_status = PaymentStatus.PENDING
                else:
                    order.payment_status = PaymentStatus.FAILED

            logger.info(f"[BG] Task finished for order {merchant_order_id}.")
        except Exception as e:
            await db.rollback()
            logger.error(f"[BG] Error processing {merchant_order_id}: {e}", exc_info=True)