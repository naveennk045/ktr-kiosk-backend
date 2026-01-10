import asyncio
import logging
from app.db.session import SessionLocal
from app.services.payment_service import PaymentService
from sqlalchemy import select
from app.db.models.edc_config import EdcConfig
from app.core.config import settings

# Mock objects
class MockRedis:
    pass

class MockHttpClient:
    pass

class MockOrderService:
    pass

async def verify_lookup():
    store_id = "KTRVER01"
    merchant_id = "HIMALAYANSAVOUROFFLINE"

    async with SessionLocal() as db:
        # Simulate the logic in initiate_edc
        stmt_config = select(EdcConfig).where(
            EdcConfig.store_id == store_id,
            EdcConfig.merchant_id == merchant_id
        )
        config_entry = (await db.execute(stmt_config)).scalar_one_or_none()

        if config_entry:
            print(f"SUCCESS: Found config for {store_id}")
            print(f"Terminal ID: {config_entry.terminal_id}")
            expected_tid = "MST2512231222094026998326"
            if config_entry.terminal_id == expected_tid:
                print("SUCCESS: Terminal ID matches expected value.")
            else:
                print(f"FAILURE: Expected {expected_tid}, got {config_entry.terminal_id}")
        else:
            print(f"FAILURE: Config not found for {store_id}")

if __name__ == "__main__":
    asyncio.run(verify_lookup())
