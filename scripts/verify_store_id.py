import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from unittest.mock import AsyncMock, MagicMock
from app.services.payment_service import PaymentService
from app.db.models.order import Order, PaymentStatus, PaymentMethod
from app.core.config import settings

async def verify():
    # Mock dependencies
    db_session = AsyncMock()
    http_client = AsyncMock()
    redis_client = MagicMock()
    order_service = AsyncMock()

    # Create service
    service = PaymentService(db_session, http_client, redis_client, order_service)

    # Mock Order
    order_id = "ORDER_123"
    order = Order(
        order_id=order_id,
        payment_status=PaymentStatus.PENDING,
        items=[],
        payment_method=None,
        qr_string=None,
        provider_resp=None
    )

    # 1. Test initiate_qr with store_id
    store_id_1 = "STORE_QR_1"

    # Setup DB mock to return this order
    mock_result_order = MagicMock()
    mock_result_order.scalar_one_or_none.return_value = order
    db_session.execute.return_value = mock_result_order

    # Mock HTTP response
    resp_mock = MagicMock()
    resp_mock.raise_for_status = MagicMock()
    resp_mock.json = MagicMock(return_value={
        "code": "SUCCESS",
        "data": {"qrCode": "QR_DATA"}
    })
    http_client.post.return_value = resp_mock

    print(f"Testing initiate_qr with store_id={store_id_1}...")
    try:
        await service.initiate_qr(order_id, 1000, store_id=store_id_1)
        if order.store_id == store_id_1:
            print("✅ initiate_qr saved store_id correctly.")
        else:
            print(f"❌ initiate_qr failed. Expected {store_id_1}, got {order.store_id}")
    except Exception as e:
        print(f"❌ initiate_qr raised exception: {e}")

    # Reset order stats for next test
    order.store_id = None
    order.payment_status = PaymentStatus.PENDING
    order.provider_resp = None

    # 2. Test initiate_edc with store_id
    store_id_2 = "STORE_EDC_1"
    merchant_id = "MERCH_1"

    # Mock EdcConfig
    mock_config = MagicMock()
    mock_config.terminal_id = "TERM_1"

    mock_result_config = MagicMock()
    mock_result_config.scalar_one_or_none.return_value = mock_config

    # Update side_effect for execute: first call returns order, second returns config
    # Note: initiate_edc calls: select(Order) -> execute; select(EdcConfig) -> execute
    db_session.execute.side_effect = [mock_result_order, mock_result_config]

    print(f"Testing initiate_edc with store_id={store_id_2}...")
    try:
        await service.initiate_edc(order_id, 1000, store_id=store_id_2, merchant_id=merchant_id)
        if order.store_id == store_id_2:
            print("✅ initiate_edc saved store_id correctly.")
        else:
            print(f"❌ initiate_edc failed. Expected {store_id_2}, got {order.store_id}")
    except Exception as e:
        print(f"❌ initiate_edc raised exception: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(verify())
    except ImportError:
        # Fallback if dependencies are missing in environment (unlikely given metadata)
        print("Could not run verification due to import errors. Environment might be restricted.")
