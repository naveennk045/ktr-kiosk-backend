from sqlalchemy import Column, Integer, String
from app.db.session import Base

class EdcConfig(Base):
    __tablename__ = "edc_config"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(String, index=True, nullable=False)
    store_id = Column(String, index=True, nullable=False)
    terminal_id = Column(String, nullable=False)
    mid_on_device = Column(String, nullable=True)
    tid_on_device = Column(String, nullable=True)
