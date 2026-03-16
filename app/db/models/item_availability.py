from sqlalchemy import Column, String, Boolean, DateTime, func
from app.db.session import Base

class ItemAvailability(Base):
    __tablename__ = "item_availability"

    sku_code = Column(String, primary_key=True, index=True)
    is_available = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
