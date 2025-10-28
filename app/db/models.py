from datetime import datetime
from beanie import Document, Link
from pydantic import BaseModel, Field
from typing import List, Optional

from sqlalchemy import JSON, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))

    menu_legacy_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # store chosen customizations/addons snapshot
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    order: Mapped[Order] = relationship(back_populates="items")
    
class CustomizationOption(BaseModel):
    value: str
    label: str
    price_impact: float = 0


class Customization(BaseModel):
    id: str
    name: str
    type: str
    options: List[CustomizationOption]
    required: bool = False


class Addon(BaseModel):
    id: str
    name: str
    price: float


class Category(Document):
    """
    A Category document.
    We add 'legacy_id' to store the original 'id' from the JSON.
    """
    name: str
    description: Optional[str] = None
    legacy_id: int = Field(..., unique=True)  #

    class Settings:
        name = "categories"


class MenuItem(Document):
    """
    A MenuItem document.
    It links to a Category and embeds customizations/addons.
    """
    name: str
    description: Optional[str] = None
    price: float
    imageSrc: str

    category: Link[Category]
    customizations: List[Customization] = []
    addons: List[Addon] = []

    legacy_id: int = Field(..., unique=True)

    class Settings:
        name = "menu_items"  # This is the collection name in MongoDB


