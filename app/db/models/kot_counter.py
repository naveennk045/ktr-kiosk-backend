from sqlalchemy import Column, ForeignKey, Integer, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.db.session import Base

class KotCounter(Base):
    __tablename__ = "kot_counters"
    __table_args__ = (
        UniqueConstraint("store_id", "kot_date", name="uq_kot_counter_store_date"),
    )

    id = Column(Integer, primary_key=True)
    store_id = Column(
        Integer,
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kot_date = Column(Date, nullable=False, index=True)
    last_number = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<KotCounter(date={self.kot_date}, last_number={self.last_number})>"