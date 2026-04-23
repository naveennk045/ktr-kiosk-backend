from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from app.db.session import Base


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_code = Column(String(32), nullable=False, unique=True, index=True)
    store_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    petpooja_credentials = relationship(
        "StorePetpoojaCredentials",
        back_populates="store",
        uselist=False,
        cascade="all, delete-orphan",
    )
    phonepe_credentials = relationship(
        "StorePhonePeCredentials",
        back_populates="store",
        uselist=False,
        cascade="all, delete-orphan",
    )
    pinelabs_credentials = relationship(
        "StorePinelabsCredentials",
        back_populates="store",
        uselist=False,
        cascade="all, delete-orphan",
    )
    kiosk_terminals = relationship(
        "KioskTerminal",
        back_populates="store",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Store(id={self.id}, store_code={self.store_code!r})>"


class StorePetpoojaCredentials(Base):
    """Per-store Petpooja restaurant credentials (one restaurant per store)."""

    __tablename__ = "store_petpooja_credentials"
    __table_args__ = (
        UniqueConstraint("petpooja_restaurant_id", name="uq_petpooja_restaurant_id"),
        UniqueConstraint("menu_sharing_code", name="uq_petpooja_menu_sharing_code"),
    )

    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="CASCADE"),
        primary_key=True,
    )
    app_key = Column(String(512), nullable=False)
    app_secret = Column(String(512), nullable=False)
    access_token = Column(Text, nullable=False)
    petpooja_restaurant_id = Column(String(64), nullable=False, index=True)
    # Petpooja "menu sharing code" — use as restID in order payload and fetch-menu API (avoids unauthorized errors).
    menu_sharing_code = Column(String(64), nullable=False, index=True)
    fetch_menu_url = Column(Text, nullable=False)
    create_order_url = Column(Text, nullable=False)
    callback_url = Column(Text, nullable=False)

    store = relationship("Store", back_populates="petpooja_credentials")


class StorePhonePeCredentials(Base):
    """Per-store PhonePe merchant / terminal credentials for QR and status APIs."""

    __tablename__ = "store_phonepe_credentials"

    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="CASCADE"),
        primary_key=True,
    )
    merchant_id = Column(String(128), nullable=False)
    salt_key = Column(String(512), nullable=False)
    salt_key_index = Column(String(16), nullable=False)
    phonepe_store_id = Column(String(128), nullable=False)
    terminal_id = Column(String(128), nullable=False)
    x_provider_id = Column(String(128), nullable=False)

    store = relationship("Store", back_populates="phonepe_credentials")


class StorePinelabsCredentials(Base):
    """Shared PineLabs Cloud EDC API credentials for all terminals under this store."""

    __tablename__ = "store_pinelabs_credentials"

    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="CASCADE"),
        primary_key=True,
    )
    base_url = Column(Text, nullable=False)
    merchant_id = Column(String(128), nullable=False)
    user_id = Column(String(128), nullable=False)
    security_token = Column(Text, nullable=False)

    store = relationship("Store", back_populates="pinelabs_credentials")


class KioskTerminal(Base):
    """Per-device terminal row: PineLabs ClientID + per-terminal PineLabs StoreID."""

    __tablename__ = "kiosk_terminals"
    __table_args__ = (
        UniqueConstraint("store_id", "terminal_id", name="uq_kiosk_terminal_store_terminal"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    terminal_id = Column(String(128), nullable=False)
    pinelabs_store_id = Column(String(128), nullable=False)
    mid_on_device = Column(String(128), nullable=True)
    label = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))

    store = relationship("Store", back_populates="kiosk_terminals")
