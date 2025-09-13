from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, UniqueConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class Product(Base):
    __tablename__ = "products"
    sku: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(400), nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Price(Base):
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(100), ForeignKey("products.sku", ondelete="CASCADE"), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    unit_minor: Mapped[int] = mapped_column(BigInteger)  # price per unit (minor)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("sku", "currency", name="uq_price_sku_currency"),)

class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(100), index=True)
    sku: Mapped[str] = mapped_column(String(100), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("store_id", "sku", name="uq_inventory_store_sku"),)

class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(100), index=True)
    sku: Mapped[str] = mapped_column(String(100), index=True)
    delta: Mapped[int] = mapped_column(Integer)  # positive for restock, negative for sale/adjustment
    reason: Mapped[str] = mapped_column(String(40), default="restock")  # restock|sale|adjustment
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)