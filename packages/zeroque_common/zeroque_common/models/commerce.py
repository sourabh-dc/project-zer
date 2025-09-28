from sqlalchemy import String, Integer, BigInteger, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class Order(Base):
    __tablename__ = "orders"
    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    site_id: Mapped[str] = mapped_column(String(100), index=True)
    store_id: Mapped[str] = mapped_column(String(100), index=True)
    shopper_id: Mapped[str] = mapped_column(String(100), index=True)
    cost_centre_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)  # e.g., 'aifi'
    provider_order_id: Mapped[str] = mapped_column(String(200), index=True)
    total_minor: Mapped[int] = mapped_column(BigInteger)  # total in minor units
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    status: Mapped[str] = mapped_column(String(20), default="completed")  # MVP single status
    occurred_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.order_id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer)
    price_minor: Mapped[int] = mapped_column(BigInteger)  # per item price in minor units