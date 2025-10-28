from typing import List

from fastapi import APIRouter, HTTPException

from app.db.models import Category, MenuItem


router = APIRouter(prefix="/menu", tags=["menu"])


@router.get("/categories", response_model=List[Category])
async def list_categories():
    categories = await Category.find_all().to_list()
    return categories


@router.get("/categories/{category_id}/items", response_model=List[MenuItem])
async def list_items_by_category(category_id: int):
    category = await Category.find_one(Category.legacy_id == category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    items = await MenuItem.find(MenuItem.category.id == category.id).to_list()
    return items


