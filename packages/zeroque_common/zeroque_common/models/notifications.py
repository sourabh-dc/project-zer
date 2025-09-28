from sqlalchemy import String, Integer, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    target_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="dev")  # dev|email|webhook
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)