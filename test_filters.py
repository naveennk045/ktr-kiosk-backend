import asyncio
from sqlalchemy import select, create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app.db.models.order import Order, PaymentMethod, OrderType, PaymentStatus

engine = create_engine("postgresql+psycopg2://postgres:postgres@localhost/kiosk")
Session = sessionmaker(bind=engine)
session = Session()

# Check how many orders have CARD payment method
print("CARD count:", session.query(Order).filter(Order.payment_method == PaymentMethod.CARD).count())
print("DINEIN count:", session.query(Order).filter(Order.order_type == OrderType.DINEIN).count())

