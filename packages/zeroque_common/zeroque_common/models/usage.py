from sqlalchemy import String, Integer, Date, DateTime, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class UsageMeter(Base):
    __tablename__ = "usage_meters"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)  # orders, unique_shoppers, etc.
    description: Mapped[str] = mapped_column(String(255), default="")

class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    site_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    store_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    meter_code: Mapped[str] = mapped_column(String(100), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g., shopper_id
    value: Mapped[int] = mapped_column(Integer, default=1)
    occurred_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class UsageAggregateDaily(Base):
    __tablename__ = "usage_aggregates_daily"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    day: Mapped["Date"] = mapped_column(Date, index=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    site_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    store_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    meter_code: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("day", "tenant_id", "site_id", "store_id", "meter_code", name="uq_daily_bucket"),)