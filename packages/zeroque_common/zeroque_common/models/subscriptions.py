from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, UniqueConstraint, DateTime, func, Text, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class SubscriptionPlan(Base):
    """Subscription plans with pricing"""
    __tablename__ = "subscription_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # core, pro, enterprise
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    price_yearly_minor: Mapped[int] = mapped_column(BigInteger)  # price in minor units (pence)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

class Feature(Base):
    """Features that can be enabled/disabled per plan"""
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # e.g., "advanced_pricing", "bulk_orders"
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=True)  # e.g., "pricing", "orders", "analytics"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PlanFeature(Base):
    """Which features are included in which plans"""
    __tablename__ = "plan_features"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_code: Mapped[str] = mapped_column(String(50), ForeignKey("subscription_plans.code", ondelete="CASCADE"), index=True)
    feature_code: Mapped[str] = mapped_column(String(50), ForeignKey("features.code", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    limits: Mapped[dict] = mapped_column(JSON, nullable=True)  # e.g., {"max_stores": 10, "max_users": 100}
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("plan_code", "feature_code", name="uq_plan_feature"),)

class SiteSubscription(Base):
    """Site-level subscriptions"""
    __tablename__ = "site_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    site_id: Mapped[str] = mapped_column(String(100), index=True)
    plan_code: Mapped[str] = mapped_column(String(50), ForeignKey("subscription_plans.code"), index=True)
    payment_method: Mapped[str] = mapped_column(String(20))  # stripe, trade
    status: Mapped[str] = mapped_column(String(50), default="active")  # active, trialing, canceled, past_due
    external_id: Mapped[str] = mapped_column(String(100), index=True)  # Stripe subscription ID or trade reference
    current_period_start: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_end: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "site_id", name="uq_site_subscription"),)

class SiteBillingAccount(Base):
    """Billing accounts for sites (Stripe customer or Trade account)"""
    __tablename__ = "site_billing_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    site_id: Mapped[str] = mapped_column(String(100), index=True)
    payment_method: Mapped[str] = mapped_column(String(20))  # stripe, trade
    external_id: Mapped[str] = mapped_column(String(100), index=True)  # Stripe customer ID or trade account code
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata: Mapped[dict] = mapped_column(JSON, nullable=True)  # Additional billing info
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "site_id", "payment_method", name="uq_site_billing_account"),)

class SubscriptionUsage(Base):
    """Track usage against subscription limits"""
    __tablename__ = "subscription_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    site_id: Mapped[str] = mapped_column(String(100), index=True)
    feature_code: Mapped[str] = mapped_column(String(50), index=True)
    usage_type: Mapped[str] = mapped_column(String(50))  # e.g., "api_calls", "storage_gb", "users"
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "site_id", "feature_code", "usage_type", "period_start", name="uq_subscription_usage"),)
