import logging
import re
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
from .routers import catalog, order, admin, petpooja, itemdetails, discount
from .routers.payment import payment
from app.core.config import settings
from app.dashboard import analytics_router, orders_read_router
from app.kds.router import router as kds_router
from app.tms.router import router as tms_router

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logger import bind_log_context, request_id_var, reset_log_context, setup_logging
import json

# Configure Logging
setup_logging()
logger = logging.getLogger(__name__)


import asyncio

async def deactivate_expired_discounts_job():
    from datetime import datetime, timezone
    from sqlalchemy import update
    from app.db.models.discount import Discount
    
    while True:
        try:
            logger.info("Running background job: deactivating expired discounts...")
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                stmt = (
                    update(Discount)
                    .where(Discount.end_date < now, Discount.is_active == True)
                    .values(is_active=False)
                )
                result = await db.execute(stmt)
                await db.commit()
                logger.info(f"Background job completed. Deactivated {result.rowcount} expired discounts.")
        except Exception as e:
            logger.error(f"Error in background job deactivate_expired_discounts_job: {e}", exc_info=True)
        
        # Run every hour
        await asyncio.sleep(3600)

# Lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FastAPI application starting up...")
 
    app.state.http_client = httpx.AsyncClient()
    logger.info("HTTP client initialized successfully.")
 
    # Create tables and add missing columns to orders dynamically
    from sqlalchemy import text
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_discount_applied BOOLEAN DEFAULT FALSE;"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_id BIGINT;"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2);"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_code VARCHAR(100);"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_type VARCHAR(50);"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_value DECIMAL(10,2);"))
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE discounts ADD COLUMN IF NOT EXISTS store_id INT REFERENCES stores(id) ON DELETE CASCADE;"))
            await conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS preparing_at TIMESTAMPTZ;"))
            await conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ;"))
            await conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS order_type ordertype;"))
            await conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS options JSONB NOT NULL DEFAULT '[]'::jsonb;"))
            await conn.execute(text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS note VARCHAR(200);"))
        logger.info("PostgreSQL tables ensured and updated with discount columns.")
    except Exception as e:
        logger.error(f"Failed to apply database alterations on startup: {e}", exc_info=True)
 
    async with SessionLocal() as session:
        await ensure_default_store(session)
 
    # Redis setup...
    try:
        # Explicit pool: redis-py 8.x lowered the implicit default cap to 100 and raises
        # MaxConnectionsError immediately when exhausted. A blocking pool waits briefly instead.
        redis_pool = redis.BlockingConnectionPool.from_url(
            settings.REDIS_HOST,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            timeout=settings.REDIS_POOL_TIMEOUT,
            decode_responses=True,
            health_check_interval=30,
            socket_keepalive=True,
        )
        app.state.redis_client = redis.Redis.from_pool(redis_pool)
        await app.state.redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.error(f"Error connecting to Redis: {e}")
        app.state.redis_client = None

    # Start the background job for expired discounts
    app.state.discount_cleanup_task = asyncio.create_task(deactivate_expired_discounts_job())
    logger.info("Discount cleanup background job registered.")
 
    logger.info("FastAPI startup complete.")
    yield
 
    await app.state.http_client.aclose()
    if app.state.redis_client:
        await app.state.redis_client.close()
        logger.info("Redis connection closed.")
        
    # Cancel background task on shutdown
    if hasattr(app.state, "discount_cleanup_task"):
        app.state.discount_cleanup_task.cancel()
        try:
            await app.state.discount_cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Discount cleanup background job cancelled.")
        
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


@app.exception_handler(StarletteHTTPException)
async def http_exception_logging_handler(request: Request, exc: StarletteHTTPException):
    """Log why a 4xx/5xx was raised (the request line only has the status), then respond as usual."""
    if not request.url.path.startswith(_UNLOGGED_PREFIXES):
        logger.log(
            logging.ERROR if exc.status_code >= 500 else logging.WARNING,
            f"HTTP {exc.status_code}: {exc.detail}",
            extra={"extra_data": {"event": "http.error", "status_code": exc.status_code, "detail": exc.detail}},
        )
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_logging_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(_UNLOGGED_PREFIXES):
        return await request_validation_exception_handler(request, exc)
    logger.warning(
        f"Request validation failed: {len(exc.errors())} error(s)",
        extra={"extra_data": {"event": "http.validation_error", "errors": [
            # Drop the rejected input value: it could be a PIN or token typed into the wrong field.
            {k: v for k, v in err.items() if k not in ("input", "ctx")}
            for err in jsonable_encoder(exc.errors())
        ]}},
    )
    return await request_validation_exception_handler(request, exc)


# Paths never logged: the logs viewer itself (reading logs would write logs) and CORS preflights.
_UNLOGGED_PREFIXES = ("/admin/logs",)
# Frequent polling endpoints: logged at DEBUG while healthy so they don't bury real events.
_POLL_PATTERN = re.compile(r"^/(tms/snapshot|tms/health|kds/board|kds/health|payments/(qr|edc)/status/)")
_ORDER_IN_PATH = re.compile(r"/payments/(?:qr|edc)/status/(?P<order_id>[^/]+)")
SLOW_REQUEST_MS = 2000
_MAX_LOGGED_BODY = 4096


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """One summary line per request: method, path, status, duration, store, order, masked body."""
    path = request.url.path
    method = request.method
    if method == "OPTIONS" or path.startswith(_UNLOGGED_PREFIXES):
        return await call_next(request)

    request_id = request.headers.get("x-request-id") or str(uuid4())
    request_id_var.set(request_id)
    reset_log_context()
    bind_log_context(store_id=(request.headers.get("x-store-id") or "").strip() or None)

    body_json = None
    if method in ("POST", "PUT", "PATCH") and "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.body()
            if body:
                # Recreate the stream for downstream consumers
                async def receive():
                    return {"type": "http.request", "body": body}
                request._receive = receive
                if len(body) <= _MAX_LOGGED_BODY:
                    try:
                        body_json = json.loads(body)
                    except ValueError:
                        body_json = "<invalid_json>"
                else:
                    body_json = f"<{len(body)} bytes, not logged>"
        except Exception:
            pass

    order_match = _ORDER_IN_PATH.search(path)
    bind_log_context(
        order_id=(body_json.get("order_id") if isinstance(body_json, dict) else None)
        or (order_match.group("order_id") if order_match else None)
    )

    started = time.perf_counter()
    fields = {
        "event": "http.request",
        "method": method,
        "path": path,
        "query": request.url.query or None,
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
    if body_json is not None:
        fields["request_body"] = body_json

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception(
            f"{method} {path} failed after {elapsed_ms} ms",
            extra={"extra_data": {**fields, "status_code": 500, "duration_ms": elapsed_ms}},
        )
        # Answer here (instead of re-raising) so the traceback is logged once, not again by uvicorn,
        # and the caller gets the request id to quote when reporting the error.
        return JSONResponse(
            {"detail": "Internal server error", "request_id": request_id},
            status_code=500,
            headers={"X-Request-Id": request_id},
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-Id"] = request_id
    status_code = response.status_code
    if status_code >= 500:
        level = logging.ERROR
    elif status_code >= 400 or elapsed_ms >= SLOW_REQUEST_MS:
        level = logging.WARNING
    elif method == "GET" and _POLL_PATTERN.match(path):
        level = logging.DEBUG
    else:
        level = logging.INFO
    logger.log(
        level,
        f"{method} {path} → {status_code} in {elapsed_ms} ms" + (" (slow)" if elapsed_ms >= SLOW_REQUEST_MS else ""),
        extra={"extra_data": {**fields, "status_code": status_code, "duration_ms": elapsed_ms}},
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
app.include_router(discount.router)
