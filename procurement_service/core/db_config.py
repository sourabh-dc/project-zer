from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base, sessionmaker

from procurement_service.core.config import SETTINGS


engine = create_engine(
    SETTINGS.DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ProcurementOrder(Base):
    __tablename__ = "procurement_orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    order_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(64))
    total_cost_minor: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    items: Mapped[list["ProcurementOrderDetail"]] = relationship(
        "ProcurementOrderDetail",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class ProcurementOrderDetail(Base):
    __tablename__ = "procurement_order_details"

    order_line_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey("procurement_orders.order_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    vendor_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(String(1024))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(Integer)
    line_total_minor: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    order: Mapped[ProcurementOrder] = relationship("ProcurementOrder", back_populates="items")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
