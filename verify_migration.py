import asyncio
import logging
import sys
from unittest.mock import MagicMock, AsyncMock
from datetime import date

# Set cached property to avoid DB access if models try to use it
from app.core.config import settings

# Mock settings values if they are None/Empty for test
if not hasattr(settings, "PETPOOJA_API_KEY") or not settings.PETPOOJA_API_KEY:
    settings.PETPOOJA_API_KEY = "test_key"
    settings.PETPOOJA_API_SECRET = "test_secret"
    settings.PETPOOJA_ACCESS_TOKEN = "test_token"
    settings.PETPOOJA_RESTAURANT_ID = "test_rest_id"
    settings.PETPOOJA_FETCH_MENU_URL = "http://test.com/menu"
    settings.PETPOOJA_CREATE_ORDER_URL = "http://test.com/order"
    settings.APP_NAME = "Test App"

from app.utils.petpooja import PetpoojaClient
from app.services.catalog_service import CatalogService
from app.services.order_service import OrderService
from app.db.models.order import Order, OrderType, PaymentMethod, KdsStatus, PaymentStatus

# Setup logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

async def test_catalog_mapping():
    print("STEP 1: Testing Catalog Mapping...", flush=True)

    # Mock specifics
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None # Cache miss

    mock_http = AsyncMock()
    mock_pp_client = PetpoojaClient(mock_http)

    # Sample Petpooja Menu Response
    mock_pp_response = {
        "success": "1",
        "taxes": [
            {"taxid": "11213", "taxname": "CGST", "tax": "2.5", "taxtype": "1"},
            {"taxid": "20375", "taxname": "SGST", "tax": "2.5", "taxtype": "1"}
        ],
        "categories": [
            {"categoryid": "500773", "categoryname": "Pizza", "active": "1", "category_image_url": "http://img.com/cat.jpg"}
        ],
        "items": [
            {
                "itemid": "118829149",
                "itemname": "Veg Loaded Pizza",
                "price": "100",
                "active": "1",
                "item_tax": "11213,20375",
                "item_categoryid": "500773"
            }
        ]
    }

    # Mock fetch_menu
    mock_pp_client.fetch_menu = AsyncMock(return_value=mock_pp_response)

    service = CatalogService(mock_redis, mock_pp_client)

    print("   Calling get_catalog...", flush=True)
    result = await service.get_catalog("test_channel")
    print("   get_catalog returned.", flush=True)

    # Assertions
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["skuCode"] == "118829149"
    assert item["itemName"] == "Veg Loaded Pizza"
    assert "11213" in item["taxTypeIds"]
    assert "20375" in item["taxTypeIds"]

    assert len(result["categories"]) == 1
    assert result["categories"][0]["imageURL"] == "http://img.com/cat.jpg"

    print("✅ Catalog Mapping Verified", flush=True)
    return result

async def test_order_pushing(catalog_data):
    print("STEP 2: Testing Order Pushing...", flush=True)

    mock_db = AsyncMock()
    # Ensure commit/refresh are awaitable
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    mock_redis = AsyncMock()
    mock_http = AsyncMock()
    mock_pp_client = PetpoojaClient(mock_http)

    # Mock catalog service to return mapped data
    mock_catalog_service = CatalogService(mock_redis, mock_pp_client)
    mock_catalog_service.get_catalog = AsyncMock(return_value=catalog_data)
    # Important: Since OrderService uses other methods of CatalogService (find_item, build_sale_item),
    # we should NOT mock the entire service if we want to test those methods.
    # But we want to mock 'get_catalog'.
    # So we use the real instance but mock the 'get_catalog' method.

    service = OrderService(mock_db, mock_catalog_service, mock_pp_client)

    # Create Dummy Order
    order = Order(
        order_id="TEST-ORDER-1",
        channel="kiosk",
        order_type=OrderType.DINEIN,
        items=[
            {"sku_code": "118829149", "quantity": 2}
        ],
        total_amount_include_tax=210.0,
        total_amount_exclude_tax=200.0,
        kot_date=date.today(),
        kot_number=1,
        kot_code="KTR-1",
        payment_method=PaymentMethod.CASH,
        payment_status=PaymentStatus.COMPLETED,
        created_at=None
    )

    # Mock Save Order Response
    mock_pp_client.save_order = AsyncMock(return_value={"success": "1", "message": "Order Saved", "restID": "12345"})

    print("   Calling sync_order_to_kds...", flush=True)
    success, invoice_id = await service.sync_order_to_kds(order)
    print(f"   sync_order_to_kds returned: {success}, {invoice_id}", flush=True)

    if not success:
        print(f"❌ Order Sync Failed! Status: {order.kds_status}, Error: {order.kds_last_error}", flush=True)

    # Verify Payload Construction indirectly via success
    assert success is True
    assert invoice_id == "12345"
    assert order.kds_status == KdsStatus.POSTED

    print("✅ Order Pushing Verified", flush=True)

async def main():
    try:
        # Run with timeout to prevent hanging
        await asyncio.wait_for(run_tests(), timeout=10.0)
    except asyncio.TimeoutError:
        print("\n❌ TEST TIMED OUT", flush=True)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}", flush=True)
        import traceback
        traceback.print_exc()

async def run_tests():
    catalog = await test_catalog_mapping()
    print(f"Catalog Keys: {list(catalog.keys())}", flush=True)

    if not catalog:
        print("❌ get_catalog returned empty/None")
        return False

    # Check for critical keys (Updated for legacy structure)
    required_keys = ["items", "taxTypes", "categories", "itemTags", "charges"]
    missing = [k for k in required_keys if k not in catalog]
    if missing:
        print(f"❌ Missing keys in catalog: {missing}")
        return False

    print("✅ Catalog Structure Verified (Keys present)")
    await test_order_pushing(catalog)
    print("\n🎉 ALL TESTS PASSED", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
