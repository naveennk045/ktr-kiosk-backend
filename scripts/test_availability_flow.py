import asyncio
import sys
import os
import json

# Add the project root to sys.path to allow imports from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete
from app.db.session import SessionLocal
from app.db.models.item_availability import ItemAvailability
from app.services.catalog_service import CatalogService
from app.core.config import settings
import redis.asyncio as redis

async def test_availability_logic():
    print("Starting verification of Item Availability Filtering...")
    
    # 1. Choose a test SKU from catalog
    # Based on response.json, '10550938' is a Cake
    test_sku = "10550938"
    channel = "test_channel"
    
    async with SessionLocal() as db:
        # Clean up any existing override for this SKU
        stmt = delete(ItemAvailability).where(ItemAvailability.sku_code == test_sku)
        await db.execute(stmt)
        await db.commit()
        
        redis_client = redis.from_url(settings.REDIS_HOST)
        service = CatalogService(redis_client, None) # No petpooja client needed for DB/Cache check
        
        print(f"\nPhase 1: Item {test_sku} should be AVAILABLE initially (if in DB/Cache)")
        catalog = await service.get_catalog(channel, db)
        items = catalog.get("items", [])
        is_present = any(str(item.get("itemId")) == test_sku for item in items)
        
        if not is_present:
            print(f"Warning: Item {test_sku} not found in catalog. Checking if it exists in first 5 items...")
            sample_ids = [str(item.get("itemId")) for item in items[:5]]
            print(f"Sample IDs: {sample_ids}")
            if items:
                test_sku = str(items[0].get("itemId"))
                print(f"Switching to test SKU: {test_sku}")
            else:
                print("Error: Catalog is empty. Cannot proceed with test.")
                return

        # 2. Mark item as UNAVAILABLE
        print(f"\nPhase 2: Marking item {test_sku} as UNAVAILABLE...")
        override = ItemAvailability(sku_code=test_sku, is_available=False)
        db.add(override)
        await db.commit()
        
        # 3. Check catalog - item should be REMOVED
        print("Fetching catalog again...")
        catalog = await service.get_catalog(channel, db)
        items = catalog.get("items", [])
        is_present = any(str(item.get("itemId")) == test_sku for item in items)
        
        if not is_present:
            print(f"SUCCESS: Item {test_sku} was REMOVED from the payload.")
        else:
            print(f"FAILURE: Item {test_sku} is still PRESENT in the payload.")
            
        # 4. Mark item as AVAILABLE again
        print(f"\nPhase 3: Marking item {test_sku} as AVAILABLE again...")
        stmt = delete(ItemAvailability).where(ItemAvailability.sku_code == test_sku)
        await db.execute(stmt)
        await db.commit()
        
        # 5. Check catalog - item should be BACK
        print("Fetching catalog again...")
        catalog = await service.get_catalog(channel, db)
        items = catalog.get("items", [])
        is_present = any(str(item.get("itemId")) == test_sku for item in items)
        
        if is_present:
            print(f"SUCCESS: Item {test_sku} is BACK in the payload.")
        else:
            print(f"FAILURE: Item {test_sku} is still MISSING from the payload.")

if __name__ == "__main__":
    try:
        asyncio.run(test_availability_logic())
    except Exception as e:
        print(f"\nError during test: {e}")
        import traceback
        traceback.print_exc()
