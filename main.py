from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from service import Repository


app = FastAPI(title="Menu API")

app.add_middleware(
   CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
async def startup_event():
    # initialize DB once on startup
    try:
        Repository.initialize_database("assets/database.json")
    except ValueError as e:
        # fail fast if DB is malformed
        raise RuntimeError(f"Failed to initialize database: {e}") from e


@app.get("/categories")
async def list_categories():
    return JSONResponse(content=Repository.get_categories())


@app.get("/categories/{category_id}/items")
async def list_items_by_category(category_id: int):
    # validate category exists
    categories = Repository.get_categories()
    if not any(cat.get("id") == category_id for cat in categories):
        raise HTTPException(status_code=404, detail="Category not found")
    items = Repository.get_items_by_category(category_id)
    return JSONResponse(content=items)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
