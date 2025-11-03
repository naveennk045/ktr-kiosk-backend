from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from app.orders.router import router as orders_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup logic (replace with your real init, e.g. await init_db())
    # open DB connections, caches, etc.
    try:

        yield
    finally:
        # shutdown logic (close DB, cleanup)
        # example: await some_shutdown_task()
        pass

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG_MODE,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/")
def home():
    return {"message": f"Welcome to {settings.APP_NAME}"}

app.include_router(orders_router)