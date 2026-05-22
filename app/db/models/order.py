import enum
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
    BigInteger,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
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


class OrderItemStatus(str, enum.Enum):
    """Kitchen / fulfilment status per line (independent of payment)."""

    NOT_ACCEPTED = "NOT_ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    COLLECTED = "COLLECTED"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_orders_order_id"),
        UniqueConstraint(
            "store_id", "kot_date", "kot_number", name="uq_orders_kot_per_store_day"
        ),
        Index("idx_orders_report", "created_at", "payment_status", "order_type"),
        Index("idx_orders_kds_sync", "payment_status", "kds_status"),
        Index("idx_orders_items_gin", "items", postgresql_using="gin"),
    )

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id = Column(String, index=True, nullable=False)
    channel = Column(String, index=True, nullable=False)

    order_type = Column(Enum(OrderType), nullable=False, index=True)

    # Legacy snapshot; new orders persist lines in `order_items`. Kept for backfill / older rows.
    items = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    total_amount_exclude_tax = Column(Numeric(10, 2), nullable=False)
    total_amount_include_tax = Column(Numeric(10, 2), nullable=False)

    takeaway_charges_exclude_tax = Column(
        Numeric(10, 2),
        nullable=False,
        server_default=text("0"),
    )
    takeaway_charges_include_tax = Column(
        Numeric(10, 2),
        nullable=False,
        server_default=text("0"),
    )

    kot_date = Column(Date, index=True, nullable=True)
    kot_number = Column(Integer, nullable=True)
    kot_code = Column(String, nullable=True, index=True)

    payment_method = Column(Enum(PaymentMethod), nullable=True)
    payment_status = Column(
        Enum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )

    terminal_id = Column(String, nullable=True, index=True)

    provider_code = Column(String, nullable=True)
    provider_txn_id = Column(String, nullable=True, index=True)
    provider_reference_id = Column(String, nullable=True)
    provider_resp = Column(JSONB, nullable=True)

    cash_pin_id = Column(Integer, ForeignKey("cash_pin.id"), nullable=True, index=True)
    cash_collected_by_staff_name = Column(String(255), nullable=True)

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

    is_discount_applied = Column(Boolean, default=False, server_default="false", nullable=False)
    discount_id = Column(BigInteger, nullable=True)
    discount_amount = Column(Numeric(10, 2), nullable=True)
    discount_code = Column(String(100), nullable=True)
    discount_type = Column(String(50), nullable=True)
    discount_value = Column(Numeric(10, 2), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
    )

    line_items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderItem.id",
    )

    def item_specs_for_payload(self) -> list:
        """Line items in the shape expected by PetpoojaPayloadBuilder (legacy JSON or relational)."""
        rel = getattr(self, "line_items", None) or []
        if rel:
            return [
                {
                    "sku_code": li.item_skuid,
                    "item_name": li.item_name,
                    "quantity": li.quantity,
                    "unit_price": float(li.price),
                    "variation_id": li.variation_id,
                    "addon_items": li.addon_items
                    if isinstance(li.addon_items, list)
                    else [],
                }
                for li in sorted(rel, key=lambda x: x.id)
            ]
        raw = self.items
        return list(raw) if raw else []

    def __repr__(self):
        return (
            f"<Order(id={self.order_id}, type={self.order_type}, "
            f"total={self.total_amount_include_tax}, status={self.payment_status})>"
        )


class OrderItem(Base):
    """
    One row per ordered line. `order_id` references `orders.id` (integer PK), not the business `orders.order_id` string.
    """

    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_order_id", "order_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(
        Integer,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_skuid = Column(String(128), nullable=False)
    item_name = Column(String(512), nullable=False)
    quantity = Column(Integer, nullable=False)
    items_need_be_ready = Column(Integer, nullable=False, server_default=text("0"))
    items_need_be_collected = Column(Integer, nullable=False, server_default=text("0"))
    price = Column(Numeric(12, 2), nullable=False)
    order_status = Column(
        Enum(OrderItemStatus),
        nullable=False,
        default=OrderItemStatus.NOT_ACCEPTED,
    )
    variation_id = Column(String(64), nullable=True)
    addon_items = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    order = relationship("Order", back_populates="line_items")

    def __repr__(self):
        return f"<OrderItem(id={self.id}, sku={self.item_skuid!r}, qty={self.quantity})>"
