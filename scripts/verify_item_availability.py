import asyncio
import sys
import os

# Add the project root to sys.path to allow imports from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.db.models.item_availability import ItemAvailability

async def verify_availability():
    async with SessionLocal() as db:
        # Count total records
        stmt = select(func.count(ItemAvailability.sku_code))
        result = await db.execute(stmt)
        count = result.scalar()
        
        print(f"Total records in item_availability: {count}")
        
        # Sample 5 records
        stmt = select(ItemAvailability).limit(5)
        result = await db.execute(stmt)
        samples = result.scalars().all()
        
        print("\nSample records:")
        for s in samples:
            print(f"SKU: {s.sku_code}, Available: {s.is_available}, Updated: {s.updated_at}")

        if count > 0:
            print("\nVerification SUCCESSFUL.")
        else:
            print("\nVerification FAILED: No records found.")

if __name__ == "__main__":
    asyncio.run(verify_availability())
