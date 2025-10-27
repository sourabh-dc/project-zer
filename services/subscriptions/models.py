import uuid
from sqlalchemy import Column, Integer, String, Text, BigInteger, Boolean, DateTime, func, ForeignKey, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID as SQLUUID

Base = declarative_base()

# Models
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, index=True, nullable=True)
    name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    price_yearly_minor = Column(BigInteger, nullable=True)
    currency = Column(String(3), nullable=True)
    active = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

class Feature(Base):
    __tablename__ = "features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanFeature(Base):
    __tablename__ = "plan_features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code"), nullable=False)
    feature_code = Column(String(50), ForeignKey("features.code"), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    limits = Column(JSON, nullable=True)  # e.g., {"rate_limit": 1000} or {"tier": "basic"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(100), unique=True, index=True, nullable=True)
    plan_code = Column(String(50), nullable=True)
    payment_method = Column(String(20), nullable=True)
    status = Column(String(50), nullable=True)
    external_id = Column(String(100), index=True, nullable=True)
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    trial_end = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

class SiteBillingAccount(Base):
    __tablename__ = "site_billing_accounts"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), index=True, nullable=False)
    site_id = Column(SQLUUID(as_uuid=True), index=True, nullable=False)
    payment_method = Column(String(20), nullable=False)
    external_id = Column(String(100), index=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    account_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    aggregate_id = Column(SQLUUID(as_uuid=True), nullable=True)
    event_data = Column(JSON, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(SQLUUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(SQLUUID(as_uuid=True), nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())