import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, JSON, Numeric, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    price_yearly_minor = Column(Integer, nullable=True)
    price_monthly_minor = Column(Integer, nullable=True)
    currency = Column(String(3), default="GBP", nullable=False)
    billing_cycle = Column(String(20), default="monthly")  # kept for compatibility
    active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow)


class PlanCatalog(Base):
    __tablename__ = "plan_catalog"
    plan_id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    meta = Column(JSONB, nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow)


class PlanPriceCatalog(Base):
    __tablename__ = "plan_price_catalog"
    plan_price_id = Column(Integer, primary_key=True, autoincrement=True)
    plan_code = Column(String(50), ForeignKey("plan_catalog.code", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    currency = Column(String(3), default="GBP", nullable=False)
    price_monthly_minor = Column(Integer, nullable=False)
    quarterly_discount_pct = Column(Numeric(5, 2), nullable=False, server_default=text("5.0"))
    yearly_discount_pct = Column(Numeric(5, 2), nullable=False, server_default=text("10.0"))
    price_quarterly_minor = Column(Integer, nullable=False)
    price_yearly_minor = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow)


class PlanPrice(Base):
    __tablename__ = "plan_prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_code = Column(
        String(50),
        ForeignKey("subscription_plans.code", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    currency = Column(String(3), default="GBP", nullable=False)
    price_monthly_minor = Column(Integer, nullable=False)
    quarterly_discount_pct = Column(Numeric(5, 2), nullable=False, server_default=text("5.0"))
    yearly_discount_pct = Column(Numeric(5, 2), nullable=False, server_default=text("10.0"))
    price_quarterly_minor = Column(Integer, nullable=False)
    price_yearly_minor = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow)


class Feature(Base):
    __tablename__ = "features"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    cluster = Column(String(50), nullable=True)
    usage_type = Column(String(50), nullable=False, default="count")
    max_unit = Column(String(50), nullable=True)
    reset_period = Column(String(20), nullable=False, default="monthly")
    active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class PlanFeature(Base):
    __tablename__ = "plan_features"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code", ondelete="CASCADE"), nullable=False, index=True)
    feature_code = Column(String(50), ForeignKey("features.code", ondelete="CASCADE"), nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    limits = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.utcnow)


class Role(Base):
    __tablename__ = "roles"
    role_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class Permission(Base):
    __tablename__ = "permissions"
    permission_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(150), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(PGUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id = Column(PGUUID(as_uuid=True), ForeignKey("permissions.permission_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))

