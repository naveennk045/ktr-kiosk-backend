import enum
from sqlalchemy import (
    Column, Integer, String, DateTime, Enum,
    UniqueConstraint, Date, Numeric, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.session import Base

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class PaymentMethod(str, enum.Enum):
    QR = "QR"
    CARD = "CARD"
    MANUAL = "MANUAL"
    CASH = "CASH"

class KdsStatus(str, enum.Enum):
    NOT_POSTED = "NOT_POSTED"
    PENDING = "PENDING"
    POSTED = "POSTED"
    FAILED = "FAILED"

class OrderType(str, enum.Enum):
    DINEIN = "DINEIN"
    TAKEAWAY = "TAKEAWAY"

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_orders_order_id"),
        UniqueConstraint("kot_date", "kot_number", name="uq_orders_kot_per_day"),
        Index("idx_orders_report", "created_at", "payment_status", "order_type"),
        Index("idx_orders_kds_sync", "payment_status", "kds_status"),
        Index("idx_orders_items_gin", "items", postgresql_using="gin"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, index=True, nullable=False)
    channel = Column(String, index=True, nullable=False)

    order_type = Column(Enum(OrderType), nullable=False, index=True)

    items = Column(JSONB, nullable=False)

    total_amount_exclude_tax = Column(Numeric(10, 2), nullable=False)
    total_amount_include_tax = Column(Numeric(10, 2), nullable=False)

    kot_date = Column(Date, index=True, nullable=False)
    kot_number = Column(Integer, nullable=False)
    kot_code = Column(String, nullable=False, index=True)

    payment_method = Column(Enum(PaymentMethod), nullable=True)
    payment_status = Column(
        Enum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )

    store_id = Column(String, nullable=True, index=True)

    provider_code = Column(String, nullable=True)
    provider_txn_id = Column(String, nullable=True, index=True)
    provider_reference_id = Column(String, nullable=True)
    provider_resp = Column(JSONB, nullable=True)

    qr_string = Column(String, nullable=True)
    qr_expires_at = Column(DateTime(timezone=True), nullable=True)

    kds_invoice_id = Column(String, nullable=True, index=True)
    kds_status = Column(
        Enum(KdsStatus),
        default=KdsStatus.NOT_POSTED,
        nullable=False,
        index=True,
    )
    kds_last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    kds_last_error = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
    )

    def __repr__(self):
        return (
            f"<Order(id={self.order_id}, type={self.order_type}, "
            f"total={self.total_amount_include_tax}, status={self.payment_status})>"
        )
