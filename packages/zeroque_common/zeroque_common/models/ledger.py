from sqlalchemy import String, Integer, BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

# Accounts we use in MVP:
# - CostCentreSpend   (debit when spending)
# - TenantClearing    (credit to offset spend)
class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)

    # Accounting
    account: Mapped[str] = mapped_column(String(40), index=True)      # CostCentreSpend | TenantClearing
    entry_type: Mapped[str] = mapped_column(String(10), default="debit")  # debit | credit
    amount_minor: Mapped[int] = mapped_column(BigInteger)             # positive minor units
    currency: Mapped[str] = mapped_column(String(3), default="GBP")

    # Dimensions
    cost_centre_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    site_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    store_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)

    # Reference
    reference_type: Mapped[str] = mapped_column(String(50))  # 'order'
    reference_id: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), default="")

    occurred_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)