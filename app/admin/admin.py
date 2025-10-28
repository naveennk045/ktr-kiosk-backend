from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db.models import Category, MenuItem


router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def admin_home(request: Request):
    # Landing page for admin; links to sections you can edit
    return templates.TemplateResponse("admin/index.html", {"request": request})


# --------- Categories CRUD (Mongo) ---------

@router.get("/categories", response_class=HTMLResponse)
async def categories_list(request: Request):
    categories: List[Category] = await Category.find_all().to_list()
    return templates.TemplateResponse("admin/categories/list.html", {"request": request, "categories": categories})


@router.get("/categories/new", response_class=HTMLResponse)
async def categories_new(request: Request):
    return templates.TemplateResponse("admin/categories/new.html", {"request": request})


@router.post("/categories/new")
async def categories_create(name: str = Form(...), description: Optional[str] = Form(None)):
    cat = Category(name=name, description=description, legacy_id=0)
    # legacy_id is unique; for admin-created categories, derive a new highest id
    last = await Category.find_all().sort("-legacy_id").limit(1).to_list()
    next_id = (last[0].legacy_id + 1) if last else 1
    cat.legacy_id = next_id
    await cat.create()
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


@router.get("/categories/{legacy_id}/edit", response_class=HTMLResponse)
async def categories_edit(legacy_id: int, request: Request):
    cat = await Category.find_one(Category.legacy_id == legacy_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return templates.TemplateResponse("admin/categories/edit.html", {"request": request, "category": cat})


@router.post("/categories/{legacy_id}/edit")
async def categories_update(legacy_id: int, name: str = Form(...), description: Optional[str] = Form(None)):
    cat = await Category.find_one(Category.legacy_id == legacy_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.name = name
    cat.description = description
    await cat.save()
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


@router.post("/categories/{legacy_id}/delete")
async def categories_delete(legacy_id: int):
    cat = await Category.find_one(Category.legacy_id == legacy_id)
    if cat:
        await cat.delete()
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


# --------- Menu Items (basic list; editing can be added similarly) ---------

@router.get("/items", response_class=HTMLResponse)
async def items_list(request: Request):
    items: List[MenuItem] = await MenuItem.find_all().to_list()
    return templates.TemplateResponse("admin/items/list.html", {"request": request, "items": items})


