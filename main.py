from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List

from config import settings
from models import Category, MenuItem

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
    """
    Initialize the Beanie connection to MongoDB
    """
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(settings.DB_URL)

    # --- THIS IS THE FIX ---
    # Explicitly set the database name, e.g., "restaurant_db"
    await init_beanie(
        database=client.restaurant_db,  # <- CHANGED
        document_models=[Category, MenuItem]  # Tell Beanie about our models
    )
    # Added a more descriptive print message
    print(f"Connection to database '{client.restaurant_db.name}' successful!")
# --- API Endpoints ---

@app.get("/")
def home():
    return {"message": f"Welcome to {settings.APP_NAME}"}


@app.get("/categories", response_model=List[Category])
async def list_categories():
    """
    Get all categories from the MongoDB 'categories' collection.
    """
    categories = await Category.find_all().to_list()
    return categories


@app.get("/categories/{category_id}/items", response_model=List[MenuItem])
async def list_items_by_category(category_id: int):
    """
    Get all menu items that belong to a specific category.
    We query by the 'legacy_id' we saved.
    """

    category = await Category.find_one(Category.legacy_id == category_id)

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    items = await MenuItem.find(MenuItem.category.id == category.id).to_list()
    return items

