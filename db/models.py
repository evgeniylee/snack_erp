from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime

from db.database import Base


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, index=True)

    item = Column(String, nullable=False)
    type = Column(String, nullable=False)

    quantity = Column(Float, nullable=False)

    place = Column(String, nullable=True)
    revenue = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class TechCard(Base):
    __tablename__ = "tech_cards"

    id = Column(Integer, primary_key=True, index=True)

    product = Column(String, nullable=False)
    raw_item = Column(String, nullable=False)
    grams_per_unit = Column(Float, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class ProductPrice(Base):
    __tablename__ = "product_prices"

    id = Column(Integer, primary_key=True, index=True)

    product = Column(String, nullable=False)
    place = Column(String, nullable=False)
    price = Column(Float, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class RawMaterialPrice(Base):
    __tablename__ = "raw_material_prices"

    id = Column(Integer, primary_key=True, index=True)

    raw_item = Column(String, nullable=False)
    price_per_kg = Column(Float, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, nullable=False, index=True)
    role = Column(String, nullable=False)
