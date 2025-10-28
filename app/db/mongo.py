from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from config import settings
from .models import  Category, MenuItem


async def init_mongo() -> None:
    client = AsyncIOMotorClient(settings.MONGO_DB_URL)
    await init_beanie(
        database=client.restaurant_db,
        document_models=[Category, MenuItem],
    )


