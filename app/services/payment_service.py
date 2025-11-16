import logging
import httpx
import redis.asyncio as redis
from sqlalchemy import select, update
from app.db.postgres import SessionLocal
from app.db.models.order import Order, PaymentStatus, KdsStatus
from app.core.rista_utils import post_order_to_kds

logger = logging.getLogger(__name__)


async def process_webhook_in_background(
        merchant_order_id: str,
        code: str,
        payload: dict,
        http_client: httpx.AsyncClient,
        redis_client: redis.Redis,
):
    logger.info(f"Background task started for order {merchant_order_id}...")
    async with SessionLocal() as db:
        # 1) Load order and update payment fields
        stmt = select(Order).where(Order.order_id == merchant_order_id)
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            logger.error(f"Order {merchant_order_id} not found in BG task")
            return

        order.provider_code = code
        order.provider_resp = payload

        if code == "PAYMENT_SUCCESS":
            order.payment_status = PaymentStatus.COMPLETED
        elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "PAYMENT_CANCELLED"):
            order.payment_status = PaymentStatus.FAILED
        else:
            order.payment_status = PaymentStatus.PENDING

        await db.commit()
        await db.refresh(order)

        # 2) Only proceed to KDS if payment is completed
        if order.payment_status != PaymentStatus.COMPLETED:
            return

        # 3) Atomically acquire KDS posting "lock" by flipping NOT_POSTED -> PENDING
        #    This ensures only one path (webhook or status endpoint) will own the post
        result = await db.execute(
            update(Order)
            .where(
                Order.id == order.id,
                Order.kds_status == KdsStatus.NOT_POSTED,
                )
            .values(kds_status=KdsStatus.PENDING)
            .returning(Order.kds_status)
        )
        row = result.first()
        await db.commit()

        # If row is None, someone else already changed kds_status
        if not row:
            logger.info(
                f"KDS posting already in progress or done for order {order.order_id}, "
                "skipping webhook KDS call."
            )
            return

        # 4) Now THIS background task owns the KDS posting
        await db.refresh(order)
        kdssuccess, invoice = await post_order_to_kds(order, http_client, redis_client)

        # 5) Persist KDS result
        if kdssuccess and invoice:
            order.kds_invoice_id = invoice
            order.kds_status = KdsStatus.POSTED
            order.kds_last_error = None
        elif not kdssuccess:
            # Keep FAILED so /status can retry later if you want
            order.kds_status = KdsStatus.FAILED

        await db.commit()