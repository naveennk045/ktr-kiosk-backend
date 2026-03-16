import asyncio
import sys
import os

# Add the project root to sys.path to allow imports from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.models.menu import Menu
from app.db.models.item_availability import ItemAvailability

async def seed_availability():
    async with SessionLocal() as db:
        # Fetch the latest menu
        stmt = select(Menu).order_by(Menu.updated_at.desc()).limit(1)
        result = await db.execute(stmt)
        menu = result.scalar_one_or_none()

        if not menu:
            print("No menu found in the database. Please sync menu first.")
            return

        items = menu.data.get("items", [])
        print(f"Found {len(items)} items in the latest menu.")

        count = 0
        for item in items:
            sku_code = item.get("itemid")
            if not sku_code:
                continue
            
            # Default is_available based on 'active' status in Petpooja data
            is_active = item.get("active") == "1"
            
            # Check if record already exists
            stmt = select(ItemAvailability).where(ItemAvailability.sku_code == sku_code)
            result = await db.execute(stmt)
            availability = result.scalar_one_or_none()
            
            if availability:
                availability.is_available = is_active
            else:
                availability = ItemAvailability(
                    sku_code=sku_code,
                    is_available=is_active
                )
                db.add(availability)
            count += 1

        await db.commit()
        print(f"Successfully seeded/updated {count} items in item_availability table.")

if __name__ == "__main__":
    asyncio.run(seed_availability())
