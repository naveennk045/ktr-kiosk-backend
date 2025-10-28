from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List

from config import settings
from app.db.mongo import init_mongo
from app.menu.router import router as menu_router
from app.admin.admin import router as admin_router
from app.orders.router import router as orders_router

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG_MODE
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.on_event("startup")
async def init_db():
    await init_mongo()
# --- API Endpoints ---

@app.get("/")
def home():
    return {"message": f"Welcome to {settings.APP_NAME}"}


app.include_router(menu_router)
app.include_router(admin_router)
app.include_router(orders_router)


