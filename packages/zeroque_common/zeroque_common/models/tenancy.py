from sqlalchemy import String, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from zeroque_common.db.session import Base

class TenantLink(Base):
    __tablename__ = "tenant_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    child_tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    relationship: Mapped[str] = mapped_column(String(30), default="distributor")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("parent_tenant_id","child_tenant_id","relationship", name="uq_tenant_link"),)