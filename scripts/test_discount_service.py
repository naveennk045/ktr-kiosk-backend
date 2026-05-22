import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal, engine, Base
from app.db.models.discount import Discount, DiscountUsage, DiscountApplicationType, DiscountType
from app.db.models.order import Order, OrderItem, PaymentStatus, OrderType
from app.services.discount_service import DiscountService
from app.services.order_service import OrderService
from app.db.schemas.order import OrderCreateRequest, OrderItemCreate
from app.db.schemas.discount import DiscountCreate
from app.services.payment_service import PaymentService
from app.services.catalog_service import CatalogService
from app.utils.petpooja import PetpoojaClient, PetpoojaCredentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_discount_service")

class MockCatalogService:
    async def get_catalog(self, channel: str, db: AsyncSession):
        return {
            "items": [
                {
                    "skuCode": "ITEM001",
                    "itemName": "Masala Dosa",
                    "price": 120.0,
                    "categoryId": "123",
                    "isPriceIncludesTax": True,
                    "taxTypeIds": []
                }
            ],
            "taxTypes": [],
            "addongroups": []
        }

class MockPetpoojaClient:
    async def save_order(self, payload: dict):
        return {"success": "1", "orderID": "MOCK-PETPOOJA-123", "message": "Mock success"}

async def test_all():
    logger.info("Initializing tables...")
    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_discount_applied BOOLEAN DEFAULT FALSE;"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_id BIGINT;"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2);"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_code VARCHAR(100);"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_type VARCHAR(50);"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_value DECIMAL(10,2);"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE discounts ADD COLUMN IF NOT EXISTS store_id INT REFERENCES stores(id) ON DELETE CASCADE;"))

    async with SessionLocal() as db:
        # Get active store
        from app.db.models.store import Store
        store_res = await db.execute(select(Store).where(Store.is_active.is_(True)).limit(1))
        active_store = store_res.scalar_one_or_none()
        if not active_store:
            logger.warning("No active store found to test. Skipping tests.")
            return

        logger.info(f"Using active store: id={active_store.id}")

        logger.info("Cleaning up old test data...")
        await db.execute(delete(DiscountUsage))
        await db.execute(delete(Discount))
        await db.commit()

        ds = DiscountService(db)

        # 1. Insert Coupons
        logger.info("Inserting test coupons (global vs store-specific)...")
        
        # 1.1 Store-specific Coupon (Active Store)
        store_coupon = await ds.create_discount(
            DiscountCreate(
                store_id=active_store.id,
                name="STORE10",
                application_type=DiscountApplicationType.COUPON.value,
                code="STORE10",
                discount_type=DiscountType.PERCENTAGE.value,
                value=10.0,
                max_discount_amount=50.0,
                min_order_amount=100.0,
                usage_limit=5,
                start_date=datetime.now(timezone.utc) - timedelta(days=1),
                end_date=datetime.now(timezone.utc) + timedelta(days=5),
                is_active=True
            )
        )
        logger.info(f"Created STORE10 store-specific coupon (Store {active_store.id}): id={store_coupon.id}")

        # 1.2 Global Coupon (store_id = None)
        global_coupon = await ds.create_discount(
            DiscountCreate(
                store_id=None,
                name="GLOBAL20",
                application_type=DiscountApplicationType.COUPON.value,
                code="GLOBAL20",
                discount_type=DiscountType.PERCENTAGE.value,
                value=20.0,
                min_order_amount=100.0,
                usage_limit=5,
                start_date=datetime.now(timezone.utc) - timedelta(days=1),
                end_date=datetime.now(timezone.utc) + timedelta(days=5),
                is_active=True
            )
        )
        logger.info(f"Created GLOBAL20 global coupon: id={global_coupon.id}")

        # 1.3 Expired Coupon
        expired_coupon = await ds.create_discount(
            DiscountCreate(
                store_id=None,
                name="EXPIRED20",
                application_type=DiscountApplicationType.COUPON.value,
                code="EXPIRED20",
                discount_type=DiscountType.PERCENTAGE.value,
                value=20.0,
                min_order_amount=50.0,
                usage_limit=10,
                start_date=datetime.now(timezone.utc) - timedelta(days=5),
                end_date=datetime.now(timezone.utc) - timedelta(days=1),
                is_active=True
            )
        )
        logger.info(f"Created EXPIRED20 expired coupon: id={expired_coupon.id}")

        # 2. Test Validation Rules (Store-wise & Constraints)
        logger.info("Testing validation rules...")
        
        # Test 2.1: Below Minimum Amount
        res = await ds.validate_discount(
            application_type="COUPON",
            code="STORE10",
            store_id=active_store.id,
            cart_amount=50.0
        )
        logger.info(f"Validate STORE10 with 50 cart: valid={res['valid']}, msg='{res['message']}'")
        assert res["valid"] is False
        assert "Minimum order amount" in res["message"]

        # Test 2.2: Store-specific coupon at MATCHING store (Pass)
        res = await ds.validate_discount(
            application_type="COUPON",
            code="STORE10",
            store_id=active_store.id,
            cart_amount=200.0
        )
        logger.info(f"Validate STORE10 with 200 cart (Store {active_store.id}): valid={res['valid']}, amt={res.get('discount_amount')}")
        assert res["valid"] is True
        assert res["discount_amount"] == 20.0

        # Test 2.3: Store-specific coupon at DIFFERENT store (Fail)
        different_store_id = active_store.id + 100
        res = await ds.validate_discount(
            application_type="COUPON",
            code="STORE10",
            store_id=different_store_id,
            cart_amount=200.0
        )
        logger.info(f"Validate STORE10 at different store (Store {different_store_id}): valid={res['valid']}, msg='{res['message']}'")
        assert res["valid"] is False
        assert "not found or is not valid" in res["message"]

        # Test 2.4: Global coupon at MATCHING store (Pass)
        res = await ds.validate_discount(
            application_type="COUPON",
            code="GLOBAL20",
            store_id=active_store.id,
            cart_amount=200.0
        )
        logger.info(f"Validate GLOBAL20 at matching store (Store {active_store.id}): valid={res['valid']}, amt={res.get('discount_amount')}")
        assert res["valid"] is True
        assert res["discount_amount"] == 40.0

        # Test 2.5: Global coupon at DIFFERENT store (Pass)
        res = await ds.validate_discount(
            application_type="COUPON",
            code="GLOBAL20",
            store_id=different_store_id,
            cart_amount=200.0
        )
        logger.info(f"Validate GLOBAL20 at different store (Store {different_store_id}): valid={res['valid']}, amt={res.get('discount_amount')}")
        assert res["valid"] is True
        assert res["discount_amount"] == 40.0

        # Test 2.6: Expired Coupon (Fail)
        res = await ds.validate_discount(
            application_type="COUPON",
            code="EXPIRED20",
            store_id=active_store.id,
            cart_amount=200.0
        )
        logger.info(f"Validate EXPIRED20 (expired): valid={res['valid']}, msg='{res['message']}'")
        assert res["valid"] is False
        assert "expired" in res["message"]

        # 3. Test Eligible Retrieval
        logger.info("Testing eligible discounts retrieval...")
        
        # Test 3.1: Eligible at Active Store (Cart = 150)
        eligible_active = await ds.get_eligible_discounts(
            application_type="COUPON",
            store_id=active_store.id,
            cart_amount=150.0
        )
        names_active = [d["name"] for d in eligible_active]
        logger.info(f"Eligible coupons for Store {active_store.id} (Cart = 150): {names_active}")
        assert "STORE10" in names_active
        assert "GLOBAL20" in names_active
        for d in eligible_active:
            assert d["code"] is None

        # Test 3.2: Eligible at Different Store (Cart = 150) -> Should NOT return STORE10
        eligible_diff = await ds.get_eligible_discounts(
            application_type="COUPON",
            store_id=different_store_id,
            cart_amount=150.0
        )
        names_diff = [d["name"] for d in eligible_diff]
        logger.info(f"Eligible coupons for Store {different_store_id} (Cart = 150): {names_diff}")
        assert "STORE10" not in names_diff
        assert "GLOBAL20" in names_diff

        # 4. Test Order Creation with Store-specific Discount
        logger.info("Testing Order creation with store-specific discount...")
        mock_catalog = MockCatalogService()
        mock_petpooja = MockPetpoojaClient()
        mock_creds = PetpoojaCredentials(
            app_key="test",
            app_secret="test",
            access_token="test",
            restaurant_id="test",
            menu_sharing_code="test",
            fetch_menu_url="test",
            create_order_url="test",
            callback_url="test"
        )
        
        osvc = OrderService(db, mock_catalog, mock_petpooja, active_store, mock_creds)

        order_req = OrderCreateRequest(
            channel="kiosk",
            order_type=OrderType.DINEIN,
            items=[
                OrderItemCreate(item_skuid="ITEM001", quantity=2)
            ],
            total_amount_include_tax=240.0,
            total_amount_exclude_tax=240.0,
            discount_id=store_coupon.id
        )

        order = await osvc.create_order(order_req)
        logger.info(f"Placed order with STORE10: order_id={order.order_id}, net_total={order.total_amount_include_tax}")
        
        assert order.is_discount_applied is True
        assert float(order.discount_amount) == 24.0
        assert order.discount_code == "STORE10"
        assert float(order.total_amount_include_tax) == 216.0

        # 5. Test Payment & Discount Usage Logging
        logger.info("Testing payment trigger and discount usage recording...")
        import httpx
        async with httpx.AsyncClient() as client:
            import redis.asyncio as redis
            from app.core.config import settings
            redis_client = redis.from_url(settings.REDIS_HOST)
            
            psvc = PaymentService(db, client, redis_client)
            prev_status = order.payment_status
            
            order.payment_status = PaymentStatus.COMPLETED
            await db.commit()
            
            await psvc._auto_mark_lines_preparing_if_newly_completed(order, prev_status)

            usage_stmt = select(DiscountUsage).where(DiscountUsage.order_id == order.id)
            usage_res = await db.execute(usage_stmt)
            usage_record = usage_res.scalar_one_or_none()
            
            assert usage_record is not None
            logger.info(f"Successfully recorded discount usage! id={usage_record.id}, amount={usage_record.discount_amount}")
            assert float(usage_record.discount_amount) == 24.0

            usage_count = await ds.get_usage_count(store_coupon.id)
            logger.info(f"STORE10 current usage count: {usage_count}")
            assert usage_count == 1
            
            await redis_client.aclose()

    logger.info("🎉 All Store-wise Discount Service tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_all())
