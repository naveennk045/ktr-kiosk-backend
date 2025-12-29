import enum
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Enum,
    UniqueConstraint, Date
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.session import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, enum.Enum):
    QR = "QR"
    EDC = "EDC"
    MANUAL = "MANUAL"


class KdsStatus(str, enum.Enum):
    NOT_POSTED = "NOT_POSTED"
    PENDING = "PENDING"
    POSTED = "POSTED"
    FAILED = "FAILED"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_orders_order_id"),
        UniqueConstraint("kot_date", "kot_number",
                         name="uq_orders_kot_per_day"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Global business/payment ID (used as PhonePe merchantOrderId)
    order_id = Column(String, index=True, nullable=False)

    channel = Column(String, index=True, nullable=False)
    items = Column(JSONB, nullable=False)

    total_amount_exclude_tax = Column(Float, nullable=False)
    total_amount_include_tax = Column(Float, nullable=False)

    # --- KOT (NEW) ---
    kot_date = Column(Date, index=True, nullable=False)
    kot_number = Column(Integer, nullable=False)
    kot_code = Column(String, nullable=False, index=True)  # "ktr-1"

    # --- Payment ---
    payment_method = Column(
        Enum(PaymentMethod),
        nullable=True,
        comment="Payment method: QR, EDC, or MANUAL",
    )
    payment_status = Column(
        Enum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )

    provider_code = Column(String, nullable=True)
    provider_txn_id = Column(String, nullable=True, index=True)
    provider_reference_id = Column(String, nullable=True)
    provider_resp = Column(JSONB, nullable=True)

    # QR-specific fields
    qr_string = Column(String, nullable=True)
    qr_expires_at = Column(DateTime(timezone=True), nullable=True)

    # --- KDS integration (extended) ---
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
            f"<Order(order_id={self.order_id}, kot={self.kot_code}, "
            f"status={self.payment_status}, method={self.payment_method})>"
        )
