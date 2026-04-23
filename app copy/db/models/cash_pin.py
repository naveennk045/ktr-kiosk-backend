from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from app.db.session import Base


class CashPin(Base):
    """
    Staff PINs for authorizing cash collection on the kiosk.
    PIN is unique per store.
    """

    __tablename__ = "cash_pin"
    __table_args__ = (UniqueConstraint("store_id", "pin", name="uq_cash_pin_store_pin"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pin = Column(String(64), nullable=False, index=True)
    staff_name = Column(String(255), nullable=False)

    def __repr__(self):
        return f"<CashPin(id={self.id}, staff_name={self.staff_name!r})>"
