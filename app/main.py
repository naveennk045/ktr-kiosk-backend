
from fastapi import FastAPI
from contextlib import asynccontextmanager
import httpx
import redis.asyncio as redis
# from .config import settings
from .routers import catalog  # Import your new router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # Create and store clients in app.state
    app.state.http_client = httpx.AsyncClient()

    try:
        app.state.redis_client = redis.Redis(
            host='localhost', port=6379, decode_responses=True
        )
        await app.state.redis_client.ping()
        print("Successfully connected to Redis.")
    except Exception as e:
        print(f"Error connecting to Redis: {e}")
        app.state.redis_client = None

    print("FastAPI application startup complete.")

    yield  # The application runs here

    # --- Shutdown ---
    await app.state.http_client.aclose()
    if app.state.redis_client:
        await app.state.redis_client.close()
    print("Cleaned up resources. Application shutting down.")


# Initialize FastAPI App
app = FastAPI(lifespan=lifespan)

@app.get("/")
def read_root():
    return {"message": "Welcome to the KTR, The best south indian restaurant!"}

app.include_router(catalog.router, prefix="/catalog", tags=["catalog"])