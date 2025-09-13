from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

# Monetary values in minor units (e.g., pence) for safety
class CostCentre(Base):
    __tablename__ = "cost_centres"
    cost_centre_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    manager_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

class Budget(Base):
    __tablename__ = "budgets"
    budget_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    cost_centre_id: Mapped[str] = mapped_column(String(100), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(20))  # 'monthly' | 'quarterly' | 'yearly'
    currency: Mapped[str] = mapped_column(String(3), default="GBP")  # MVP: single region, but keep column
    limit_minor: Mapped[int] = mapped_column(BigInteger)  # budget limit in minor units
    spent_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    hard_block: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("limit_minor >= 0", name="ck_budget_limit_nonneg"),
        CheckConstraint("spent_minor >= 0", name="ck_budget_spent_nonneg"),
    )

class UserCostCentre(Base):
    __tablename__ = "user_cost_centres"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    cost_centre_id: Mapped[str] = mapped_column(String(100), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("user_id", "cost_centre_id", name="uq_user_costcentre"),)