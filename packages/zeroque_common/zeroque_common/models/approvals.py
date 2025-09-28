from sqlalchemy import String, Integer, BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    cost_centre_id: Mapped[str] = mapped_column(String(100), index=True)
    requester_user_id: Mapped[str] = mapped_column(String(100), index=True)
    # scope: if set, limit to a specific user; else CC-wide
    user_scope_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    amount_minor: Mapped[int] = mapped_column(BigInteger)        # approved total
    remaining_minor: Mapped[int] = mapped_column(BigInteger)     # decremented as we consume

    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|denied
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)