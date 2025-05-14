# models.py　データベースモデルの定義
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, DateTime, Float, Numeric, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from app.database import Base
Base = Base

class User(Base):
    __tablename__ = "Users"

    user_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'), server_onupdate=text('CURRENT_TIMESTAMP'))

class PurchaseOrder(Base):
    __tablename__ = "PurchaseOrders"

    po_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("Users.user_id"))
    customer_name = Column(String(255), nullable=False)
    po_number = Column(String(50), unique=True, nullable=False)
    currency = Column(String(10), nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    payment_terms = Column(String(255), nullable=False)
    shipping_terms = Column(String(255), nullable=False)
    destination = Column(String(255), nullable=False)  
    status = Column(String(50), nullable=False, default="手配前")
    created_at = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'), server_onupdate=text('CURRENT_TIMESTAMP'))

class OrderItem(Base):
    __tablename__ = "OrderItems"

    item_id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("PurchaseOrders.po_id"))
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    subtotal = Column(Numeric(10, 2), nullable=False)

class ShippingSchedule(Base):
    __tablename__ = "ShippingSchedules"

    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("PurchaseOrders.po_id"))
    shipping_company = Column(String(255), nullable=False)
    transit_point = Column(String(255), nullable=True)
    cut_off_date = Column(Date, nullable=False)
    etd = Column(Date, nullable=False)
    eta = Column(Date, nullable=False)
    booking_number = Column(String(50), unique=True, nullable=False)
    vessel_name = Column(String(255), nullable=False)
    voyage_number = Column(String(50), nullable=False)
    container_size = Column(String(50), nullable=False)

class Log(Base):
    __tablename__ = "Logs"

    log_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("Users.user_id"))
    action = Column(String(255), nullable=False)
    processed_data = Column(Text, nullable=True)

class OCRResult(Base):
    __tablename__ = "OCRResults"

    ocr_id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("PurchaseOrders.po_id"), nullable=True)
    raw_text = Column(Text, nullable=True)  # ← Integer → Text に修正
    processed_data = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="手配前")
    ocrresultscol1 = Column(String(255), nullable=False, default="default_value") ## 3/31追加

class Input(Base):
    __tablename__ = "Input"

    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("PurchaseOrders.po_id"))
    shipment_arrangement = Column(String(255), nullable=False)
    po_acquisition_date = Column(Date, nullable=False)
    organization = Column(String(255), nullable=False)
    invoice_number = Column(String(50), nullable=False)
    payment_status = Column(String(50), nullable=False)
    booking_number = Column(String(50), nullable=True)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'), server_onupdate=text('CURRENT_TIMESTAMP'))

__all__ = ["Base", "User", "PurchaseOrder", "OrderItem", "ShippingSchedule", "Log", "OCRResult", "Input"]