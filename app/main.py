import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import httpx
import redis.asyncio as redis

from app.db.session import engine, Base
from .routers import catalog, order, admin, dashboard
from .routers.payment import payment
from app.core.config import settings

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


# Lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FastAPI application starting up...")

    app.state.http_client = httpx.AsyncClient()
    logger.info("HTTP client initialized successfully.")

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL tables ensured.")

    # Redis setup...
    try:
        app.state.redis_client = redis.from_url(
            settings.REDIS_HOST,
            decode_responses=True
        )
        await app.state.redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.error(f"Error connecting to Redis: {e}")
        app.state.redis_client = None

    logger.info("FastAPI startup complete.")
    yield

    await app.state.http_client.aclose()
    if app.state.redis_client:
        await app.state.redis_client.close()
        logger.info("Redis connection closed.")
    logger.info("Resources cleaned up. Application shutting down.")


# FastAPI App
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the KTR, The best South Indian restaurant!"}


# Routers
app.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
app.include_router(order.router, prefix="/orders", tags=["orders"])
app.include_router(payment.router, prefix="/payments", tags=["payments"])
app.include_router(dashboard.router, prefix="/analytics", tags=["analytics"])
app.include_router(admin.router)
