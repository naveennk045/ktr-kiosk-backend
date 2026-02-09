import asyncio
import logging
from app.db.session import SessionLocal, engine, Base
from app.db.models.edc_config import EdcConfig
from sqlalchemy import select
from app.core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA = [
    {
        "merchant_id": "HIMALAYANSAVOUROFFLINE",
        "store_id": "KTRVER01",
        "terminal_id": "MST2512231222094026998326",
        "mid_on_device": "37326006542202",
        "tid_on_device": "81970604"
    },
    {
        "merchant_id": "HIMALAYANSAVOUROFFLINE",
        "store_id": "KTRVER02",
        "terminal_id": "MST2512231227034880560456",
        "mid_on_device": "37326006542204",
        "tid_on_device": "81970606"
    },
    {
        "merchant_id": "HIMALAYANSAVOUROFFLINE",
        "store_id": "KTRBAN01",
        "terminal_id": "MST2512231231572536227029",
        "mid_on_device": "37326006542205",
        "tid_on_device": "81970607"
    },
    {
        "merchant_id": "HIMALAYANSAVOUROFFLINE",
        "store_id": "KTRBAN02",
        "terminal_id": "MST2512231235010551194104",
        "mid_on_device": "37326006542207",
        "tid_on_device": "81970611"
    },
    {
        "merchant_id": "HIMALAYANSAVOURUAT",
        "store_id": "teststore1",
        "terminal_id": "testterminal1",
        "mid_on_device": "0123456789",
        "tid_on_device": "9876543210"
    }
]

async def seed_data():
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        for item in DATA:
            stmt = select(EdcConfig).where(
                EdcConfig.merchant_id == item["merchant_id"],
                EdcConfig.store_id == item["store_id"]
            )
            exists = (await db.execute(stmt)).scalar_one_or_none()

            if exists:
                logger.info(f"Updating config for {item['store_id']}")
                exists.terminal_id = item["terminal_id"]
                exists.mid_on_device = item["mid_on_device"]
                exists.tid_on_device = item["tid_on_device"]
            else:
                logger.info(f"Creating config for {item['store_id']}")
                new_config = EdcConfig(**item)
                db.add(new_config)

        await db.commit()
        logger.info("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(seed_data())
