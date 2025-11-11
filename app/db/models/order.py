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


class PaymentMethod(str, enum.Enum):
    """Payment method used for the transaction"""
    QR = "QR"  # Dynamic QR code
    EDC = "EDC"  # EDC terminal (card/QR on device)
    MANUAL = "MANUAL"  # Manual/cash payment


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

    # Payment method tracking
    payment_method = Column(
        Enum(PaymentMethod),
        nullable=True,
        comment="Payment method: QR, EDC, or MANUAL"
    )

    # Provider/payment metadata
    payment_status = Column(
        Enum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True  # Add index for faster status queries
    )
    provider_code = Column(
        String,
        nullable=True,
        comment="PhonePe response code: PAYMENT_SUCCESS, PAYMENT_ERROR_xxx, etc."
    )
    provider_txn_id = Column(
        String,
        nullable=True,
        index=True,  # Add index for faster webhook lookups
        comment="Transaction ID from provider (same as order_id if reused)"
    )
    provider_reference_id = Column(
        String,
        nullable=True,
        comment="EDC reference number (RRN) or UPI transaction reference"
    )
    provider_resp = Column(
        JSONB,
        nullable=True,
        comment="Latest raw provider response JSON"
    )

    # QR-specific fields
    qr_string = Column(
        String,
        nullable=True,
        comment="QR payload to render (if provided by provider)"
    )
    qr_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="QR code expiration timestamp"
    )

    # KDS integration
    kds_invoice_id = Column(
        String,
        nullable=True,
        index=True,
        comment="Invoice ID from KDS system after successful payment"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        comment="Last updated timestamp"
    )

    def __repr__(self):
        return f"<Order(order_id={self.order_id}, status={self.payment_status}, method={self.payment_method})>"
