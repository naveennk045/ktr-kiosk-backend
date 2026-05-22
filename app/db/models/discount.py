import enum
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class DiscountApplicationType(str, enum.Enum):
    COUPON = "COUPON"
    AUTOMATIC = "AUTOMATIC"
    LOYALTY = "LOYALTY"
    REFERRAL = "REFERRAL"

class DiscountType(str, enum.Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    FREE_SHIPPING = "FREE_SHIPPING"

class Discount(Base):
    __tablename__ = "discounts"
    __table_args__ = (
        UniqueConstraint("code", "store_id", name="uq_discount_code_store"),
        CheckConstraint("value >= 0", name="chk_discount_value_non_negative"),
        CheckConstraint("end_date > start_date", name="chk_discount_valid_dates"),
        Index("idx_discount_code", "code"),
        Index("idx_discount_active", "is_active", "is_deleted"),
        Index("idx_discount_dates", "start_date", "end_date"),
        Index("idx_discount_store", "store_id", "is_active", "is_deleted"),
    )

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    application_type = Column(String(50), nullable=False) # e.g. COUPON, AUTOMATIC, LOYALTY, REFERRAL
    code = Column(String(100), nullable=True)
    discount_type = Column(String(50), nullable=False) # e.g. PERCENTAGE, FIXED_AMOUNT, FREE_SHIPPING
    value = Column(Numeric(10, 2), nullable=True)

    max_discount_amount = Column(Numeric(10, 2), nullable=True)
    min_order_amount = Column(Numeric(10, 2), nullable=True)

    usage_limit = Column(Integer, nullable=True)

    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)

    is_active = Column(Boolean, default=True, server_default="true")
    is_deleted = Column(Boolean, default=False, server_default="false")

    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    usages = relationship("DiscountUsage", back_populates="discount", cascade="all, delete-orphan")


class DiscountUsage(Base):
    __tablename__ = "discount_usages"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    discount_id = Column(BigInteger, ForeignKey("discounts.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    discount_amount = Column(Numeric(10, 2), nullable=False)
    used_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    discount = relationship("Discount", back_populates="usages")
