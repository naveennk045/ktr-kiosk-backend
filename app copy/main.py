import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import httpx
import redis.asyncio as redis

from app.db.session import engine, Base, SessionLocal
from app.db.bootstrap import ensure_default_store
from .routers import catalog, order, admin, petpooja
from .routers.payment import payment
from app.core.config import settings
from app.dashboard import analytics_router, orders_read_router

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

    async with SessionLocal() as session:
        await ensure_default_store(session)

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


# FastAPI App (OpenAPI: GET /docs, GET /redoc)
app = FastAPI(
    lifespan=lifespan,
    title="KTR Kiosk Server",
    description=(
        "Multi-store kiosk backend: catalog (Petpooja), orders, PhonePe QR, "
        "Pine Labs EDC, cash PIN, dashboard reads, and Petpooja webhooks. "
        "Per-store credentials are in PostgreSQL; env holds only DB/Redis and PhonePe API base URLs. "
        "Most routes require `X-Store-Id` (numeric store id or `store_code`); "
        "payment routes resolve the store from the order id. See docs/API.md."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "catalog", "description": "Menu catalog and Redis cache (requires X-Store-Id)."},
        {"name": "orders", "description": "Create order (POST /orders/)."},
        {"name": "dashboard", "description": "Order grid and detail for admin UI (GET /orders/)."},
        {"name": "payments", "description": "PhonePe webhook (no X-Store-Id)."},
        {"name": "Dynamic QR", "description": "PhonePe UPI QR init/status."},
        {"name": "edc", "description": "Pine Labs EDC init/status."},
        {"name": "cash", "description": "Cash payment with staff PIN."},
        {"name": "analytics", "description": "IST KPI summary (requires X-Store-Id)."},
        {
            "name": "admin",
            "description": "GET /admin/kiosk-config lists all stores (no X-Store-Id); cash-pins and cache invalidation require X-Store-Id.",
        },
        {"name": "petpooja", "description": "Inbound menu push and callbacks."},
    ],
)

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
app.include_router(orders_read_router, prefix="/orders", tags=["dashboard"])
app.include_router(payment.router, prefix="/payments", tags=["payments"])
app.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
app.include_router(admin.router)
app.include_router(petpooja.router, prefix="/petpooja", tags=["petpooja"])
