import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
from sqlalchemy.dialects.postgresql import JSONB  # Import for JSONB
from sqlalchemy.sql import func
from app.db.postgres import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, index=True, nullable=False)

    # Stores the list of items as a JSON array
    items = Column(JSONB, nullable=False)

    total_amount_exclude_tax = Column(Float, nullable=False)
    total_amount_include_tax = Column(Float, nullable=False)

    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # We no longer need the 'relationship' to OrderItem