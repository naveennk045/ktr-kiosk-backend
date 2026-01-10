import asyncio
import logging
from app.db.session import SessionLocal
from app.db.models.order import Order
from sqlalchemy import select, desc

async def verify_transactions():
    async with SessionLocal() as db:
        stmt = select(Order).order_by(desc(Order.created_at)).limit(5)
        result = await db.execute(stmt)
        orders = result.scalars().all()

        print(f"Found {len(orders)} transactions.")
        for o in orders:
            info = {
                "id": o.order_id,
                "amount": o.total_amount_include_tax,
                "status": o.payment_status
            }
            print(info)

if __name__ == "__main__":
    asyncio.run(verify_transactions())
