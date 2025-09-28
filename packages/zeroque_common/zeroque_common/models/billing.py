from sqlalchemy import String, Integer, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from zeroque_common.db.session import Base

class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")

class Feature(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

class PlanFeature(Base):
    __tablename__ = "plan_features"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_code: Mapped[str] = mapped_column(String(50), index=True)
    feature_code: Mapped[str] = mapped_column(String(100), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("plan_code", "feature_code", name="uq_plan_feature"),)

class StripeCustomer(Base):
    __tablename__ = "stripe_customers"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(100), index=True)

class TradeAccount(Base):
    __tablename__ = "trade_accounts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    ar_customer_code: Mapped[str] = mapped_column(String(100))
    terms: Mapped[str] = mapped_column(String(50), default="NET30")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    plan_code: Mapped[str] = mapped_column(String(50), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # stripe|trade
    status: Mapped[str] = mapped_column(String(50), default="active")  # active|trialing|canceled
    external_id: Mapped[str] = mapped_column(String(100), index=True)

class PaymentPreference(Base):
    __tablename__ = "payment_preferences"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    method: Mapped[str] = mapped_column(String(20))  # 'trade' | 'stripe'

class TradeInvoice(Base):
    __tablename__ = "trade_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|posted|canceled
    memo: Mapped[str] = mapped_column(Text, default="")

class StripeCharge(Base):
    __tablename__ = "stripe_charges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    status: Mapped[str] = mapped_column(String(20), default="succeeded")  # dev: mark as succeeded
    receipt_url: Mapped[str] = mapped_column(String(255), default="")
