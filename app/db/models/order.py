import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.postgres import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("order_id", name="uq_orders_order_id"),)

    id = Column(Integer, primary_key=True, index=True)

    # Your business identifier used also as PhonePe transactionId/merchantOrderId
    order_id = Column(String, index=True, nullable=False)

    channel = Column(String, index=True, nullable=False)

    # Items as JSON array
    items = Column(JSONB, nullable=False)

    # Amounts (store both if you need; paise in provider_amount_paise)
    total_amount_exclude_tax = Column(Float, nullable=False)
    total_amount_include_tax = Column(Float, nullable=False)

    # Provider/payment metadata
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    provider_code = Column(String, nullable=True)  # e.g., PAYMENT_SUCCESS / PAYMENT_ERROR_xxx
    provider_txn_id = Column(String, nullable=True)  # same as order_id if you reuse, else provider generated
    provider_resp = Column(JSONB, nullable=True)  # latest raw provider response JSON
    qr_string = Column(String, nullable=True)  # QR payload to render (if provided by provider)
    qr_expires_at = Column(DateTime(timezone=True), nullable=True)
    kds_invoice_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
