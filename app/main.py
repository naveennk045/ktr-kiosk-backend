import logging
import time
from uuid import uuid4
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
import httpx
import redis.asyncio as redis

from app.db.session import engine, Base, SessionLocal
from app.db.bootstrap import ensure_default_store
from .routers import catalog, order, admin, petpooja, itemdetails
from .routers.payment import payment
from app.core.config import settings
from app.dashboard import analytics_router, orders_read_router
from app.kds.router import router as kds_router
from app.tms.router import router as tms_router

from app.core.logger import setup_logging, request_id_var
import json

# Configure Logging
setup_logging()
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
            decode_responses=True,
            health_check_interval=30,
            socket_keepalive=True,
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
        {"name": "kds", "description": "Kitchen display: board, line status, WebSocket (requires X-Store-Id)."},
        {"name": "tms", "description": "Token display: snapshot and SSE (X-Store-Id or store_id query on stream)."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    request_id_var.set(request_id)
    
    body_json = None
    try:
        if "application/json" in request.headers.get("content-type", ""):
            body = await request.body()
            if body:
                # Recreate the stream for downstream consumers
                async def receive():
                    return {"type": "http.request", "body": body}
                request._receive = receive
                
                try:
                    body_json = json.loads(body)
                except Exception:
                    body_json = "<invalid_json>"
    except Exception:
        pass

    method = request.method
    path = request.url.path
    query = request.url.query if request.url.query else ""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "-")
    started = time.perf_counter()

    extra_data = {
        "method": method,
        "path": path,
        "query": query,
        "client_ip": client_ip,
        "user_agent": user_agent,
    }
    if body_json is not None:
        extra_data["request_body"] = body_json

    logger.info(
        f"request_started method={method} path={path}",
        extra={"extra_data": extra_data}
    )
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception(
            f"request_failed method={method} path={path} duration_ms={elapsed_ms}",
            extra={"extra_data": {"duration_ms": elapsed_ms}}
        )
        raise

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-Id"] = request_id
    logger.info(
        f"request_completed method={method} path={path} status={response.status_code} duration_ms={elapsed_ms}",
        extra={"extra_data": {"status_code": response.status_code, "duration_ms": elapsed_ms}}
    )
    return response


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
app.include_router(kds_router, prefix="/kds", tags=["kds"])
app.include_router(tms_router, prefix="/tms", tags=["tms"])
app.include_router(itemdetails.router, prefix="/itemdetails", tags=["itemdetails"])
