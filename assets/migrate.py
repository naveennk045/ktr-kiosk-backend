import asyncio
import json
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from config import settings
from app.db.models import Category, MenuItem, Addon, Customization, CustomizationOption


async def migrate_data():
    print("Starting data migration...")

    # 1. Connect to the database
    client = AsyncIOMotorClient(settings.MONGO_DB_URL)

    # --- THIS IS THE FIX ---
    # Use the *same* database name as in main.py
    await init_beanie(
        database=client.restaurant_db,  # <- CHANGED
        document_models=[Category, MenuItem]
    )

    # Updated this print message to match
    print(f"Connected to database: {client.restaurant_db.name}")

    # ... rest of your script ...

    # 2. Clear existing data (for a clean migration)
    print("Clearing existing data...")
    await MenuItem.delete_all()
    await Category.delete_all()
    print("Existing data cleared.")

    # 3. Load data from JSON
    try:
        with open("assets/database.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"FATAL: Error reading database.json: {e}")
        return

    # 4. Migrate Categories
    # This map will store: { old_json_id: new_category_object }
    category_map = {}
    json_categories = data.get("categories", [])
    print(f"Migrating {len(json_categories)} categories...")

    for cat in json_categories:
        new_category = Category(
            name=cat['name'],
            description=cat.get('description'),
            legacy_id=cat['id']
        )
        await new_category.create()
        # Store the new object for linking later
        category_map[cat['id']] = new_category

    print("Categories migration complete.")

    # 5. Migrate Menu Items
    json_items = data.get("menu_items", [])
    print(f"Migrating {len(json_items)} menu items...")

    for item in json_items:
        # Find the linked Category object from our map
        category_object = category_map.get(item['category_id'])
        if not category_object:
            print(f"Skipping item {item['name']}: invalid category_id {item['category_id']}")
            continue

        # Create the MenuItem document
        new_item = MenuItem(
            name=item['name'],
            description=item.get('description'),
            price=item['price'],
            imageSrc=item['imageSrc'],
            category=category_object,  # This creates the Beanie Link
            legacy_id=item['id'],
            # Use ** to unpack dictionaries into Pydantic models
            customizations=[Customization(**cust) for cust in item.get('customizations', [])],
            addons=[Addon(**addon) for addon in item.get('addons', [])]
        )
        await new_item.create()

    print("Menu items migration complete.")
    print("--- DATA MIGRATION SUCCESSFUL! ---")


if __name__ == "__main__":
    # Set your .env file path if it's not in the root
    # from dotenv import load_dotenv
    # load_dotenv()

    asyncio.run(migrate_data())