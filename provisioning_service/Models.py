from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, func, UUID, BigInteger, text, Text, JSON, \
    Date, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base, relationship, backref, Mapped, mapped_column
import uuid

# ==================================================================================
# DATABASE MODELS
# ==================================================================================
Base = declarative_base()

class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_name = Column(String, nullable=False, index=True)
    tenant_type = Column(String, nullable=False)  # retailer/brand/franchisee
    email = Column(String, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    registration_number = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    default_currency = Column(String(3), nullable=True)
    timezone = Column(String, nullable=True)
    locale = Column(String, nullable=True)
    billing_email = Column(String, nullable=True)
    billing_address = Column(JSONB, nullable=True)
    primary_domain = Column(String, nullable=True)
    logo = Column(String, nullable=True)
    owner_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)
    industry = Column(String, nullable=True)
    tech_contact_email = Column(String, nullable=True)
    support_contact_email = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Site(Base):
    __tablename__ = "sites"

    site_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    site_type = Column(String, nullable=False)  # mall/campus/DC/online-hub
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    currency = Column(String(3), nullable=True)
    timezone = Column(String, nullable=True)
    language = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    fax = Column(String, nullable=True)
    email = Column(String, nullable=True)
    url = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    primary_billing_address = Column(JSONB, nullable=True)
    primary_shipping_address = Column(JSONB, nullable=True)
    shipping_addresses = Column(JSONB, nullable=True)
    geo = Column(JSONB, nullable=True)
    external_id = Column(String, nullable=True)
    is_headquarter = Column(Boolean, nullable=True, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Store(Base):
    __tablename__ = "stores"

    store_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    site_id = Column(SQLUUID(as_uuid=True), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=True, index=True)

    name = Column(String, nullable=False)
    store_type = Column(String, nullable=False)  # physical/online/kiosk/darkstore
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    currency = Column(String(3), nullable=True)
    timezone = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    url = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    primary_shipping_address = Column(JSONB, nullable=True)
    pickup_address = Column(JSONB, nullable=True)
    geo = Column(JSONB, nullable=True)
    external_id = Column(String, nullable=True)
    fulfillment_mode = Column(String, nullable=True)  # pickup/ship/both
    inventory_policy = Column(String, nullable=True)  # track_on_hand

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    user_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)

    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)  # required
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    is_active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    display_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    position = Column(String, nullable=True)
    profile_image = Column(String, nullable=True)
    is_sso_enabled = Column(Boolean, nullable=True, default=False)
    home_site_id = Column(SQLUUID(as_uuid=True), ForeignKey("sites.site_id"), nullable=True)
    home_store_id = Column(SQLUUID(as_uuid=True), ForeignKey("stores.store_id"), nullable=True)
    home_org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id"), nullable=True)
    all_locations = Column(Boolean, nullable=True, default=False)

    failed_login_attempts = Column(Integer, nullable=True, default=0)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    refresh_token = Column(String, nullable=True)
    refresh_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_logout_at = Column(DateTime(timezone=True), nullable=True)
    
    # Budget and ordering limits
    max_order_limit_minor = Column(Integer, nullable=True, default=10000000)  # Default 100,000 (in minor units, e.g., cents)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_users_tenant_email_unique", "tenant_id", "email", unique=True),
    )


class Role(Base):
    """Role model - permission templates"""
    __tablename__ = "roles"
    role_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserRole(Base):
    """User-Role assignment model"""
    __tablename__ = "user_roles"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(SQLUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Permission(Base):
    """Permission catalog"""
    __tablename__ = "permissions"
    permission_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(150), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RolePermission(Base):
    """Role to permission mapping"""
    __tablename__ = "role_permissions"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_code = Column(String, ForeignKey("roles.code", ondelete="CASCADE"), nullable=False, index=True)
    permission_code = Column(String, ForeignKey("permissions.code", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantRole(Base):
    """Tenant-scoped custom roles"""
    __tablename__ = "tenant_roles"
    role_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index('ix_tenant_role_unique', 'tenant_id', 'code', unique=True),)


class TenantRolePermission(Base):
    """Permission mapping for tenant roles"""
    __tablename__ = "tenant_role_permissions"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_role_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenant_roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    permission_code = Column(String, ForeignKey("permissions.code", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantUserRole(Base):
    """User to tenant-role assignment"""
    __tablename__ = "tenant_user_roles"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_role_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenant_roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OrgUnit(Base):
    """Organisational hierarchy unit"""
    __tablename__ = "org_units"

    org_unit_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String, nullable=False)
    type = Column(String, nullable=False, index=True)  # department/division/team
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted

    parent_org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="SET NULL"), nullable=True, index=True)
    code = Column(String, nullable=True)
    description = Column(String, nullable=True)
    manager_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)
    external_id = Column(String, nullable=True)
    path = Column(String, nullable=True)
    depth = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    tenant = relationship("Tenant", backref=backref("org_units", cascade="all, delete-orphan"))
    parent = relationship("OrgUnit", remote_side=[org_unit_id], backref="children")
    manager = relationship("User", backref="managed_org_units", foreign_keys=[manager_user_id])
    users = relationship("User", backref="home_org_unit", foreign_keys="User.home_org_unit_id")


class UserOrgAssignment(Base):
    """User assignment into organisational hierarchy"""
    __tablename__ = "user_org_assignments"
    assignment_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(SQLUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())


class Vendor(Base):
    """Vendor model - suppliers and partners"""
    __tablename__ = "vendors"
    vendor_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    description = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ColourGroup(Base):
    """Colour group model - grouping colours by category"""
    __tablename__ = "colour_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    colour_name = Column(String(100), nullable=False, index=True)
    colour_group = Column(String(100), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Colour(Base):
    """Colour model - product colour definitions"""
    __tablename__ = "colours"

    colour_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, index=True)
    abbreviation = Column(String(20), nullable=True)
    colour_group = Column(String(100), nullable=True, index=True)
    source_internal_id = Column(String(100), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Size(Base):
    """Size model - product size definitions"""
    __tablename__ = "sizes"

    size_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False, index=True)
    abbreviation = Column(String(20), nullable=True)
    sort_order = Column(Integer, nullable=True, default=0)
    source_internal_id = Column(String(100), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Fit(Base):
    """Fit model - product fit types"""
    __tablename__ = "fits"

    fit_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class UosLabel(Base):
    """UOS Label model - unit of sale labels"""
    __tablename__ = "uos_labels"

    label_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, index=True)
    label_type = Column(String(50), nullable=True, index=True)
    source_id = Column(String(100), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CostCentre(Base):
    """Cost Centre model - budget tracking"""
    __tablename__ = "cost_centres"

    cost_centre_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)

    code = Column(String(50), nullable=False)  # unique per tenant
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    owner_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)

    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    is_active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CostCenterBudget(Base):
    __tablename__ = "cost_center_budget"

    # Primary key
    budget_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    cost_centre_id = Column(UUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id"), nullable=False)

    # Period info
    fiscal_year = Column(Integer, nullable=False)
    period_type = Column(String(20), nullable=False)  # annual, quarterly, monthly, custom
    period_number = Column(Integer, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)

    # Budget amounts (minor units = cents/paise)
    budget_amount_minor = Column(BigInteger, nullable=False)
    allocated_to_users_minor = Column(BigInteger, nullable=False, default=0)
    remaining_to_allocate_minor = Column(BigInteger, nullable=True)
    total_spent_minor = Column(BigInteger, nullable=False, default=0)
    lapsed_amount_minor = Column(BigInteger, nullable=True)

    # Status
    status = Column(String(20), nullable=False)  # draft, active, closed
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserCostCentre(Base):
    __tablename__ = "user_cost_centres"
    # Primary key
    user_budget_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    cost_centre_id = Column(UUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id"), nullable=False)
    cc_budget_id = Column(UUID(as_uuid=True), ForeignKey("cost_center_budget.budget_id"), nullable=False)

    # Budget allocations
    max_budget_minor = Column(BigInteger, nullable=False)  # admin-set cap
    allocated_minor = Column(BigInteger, nullable=False)  # allocated from CC
    spent_minor = Column(BigInteger, nullable=False)  # amount spent
    available_minor = Column(BigInteger, nullable=False)  # allocated - spent
    recurring_amount_minor = Column(BigInteger, nullable=False)  # recurring allocation amount

    # Recurring info
    recurring_period = Column(String(20), nullable=True)  # weekly, monthly, etc.
    next_recurring_at = Column(DateTime(timezone=True), nullable=True)

    # Blocking info
    is_blocked = Column(Boolean, nullable=False, default=False)
    blocked_reason = Column(String(255), nullable=True)
    blocked_at = Column(DateTime(timezone=True), nullable=True)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="cost_centres", foreign_keys=[user_id])
    cost_centre = relationship("CostCentre", back_populates="members", foreign_keys=[cost_centre_id])
    cc_budget = relationship("CostCenterBudget", foreign_keys=[cc_budget_id])


class SubscriptionPlan(Base):
    """Subscription plan"""
    __tablename__ = "subscription_plans"
    plan_id = Column(SQLUUID(as_uuid=True), primary_key=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=func.now())


class PlanPrice(Base):
    __tablename__ = "plan_price"
    plan_price_id = Column(Integer, primary_key=True, autoincrement=True)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    currency = Column(String(3), default="GBP", nullable=False)
    price_monthly_minor = Column(Numeric, nullable=False)
    quarterly_discount_pct = Column(Numeric(5, 2), nullable=False, server_default=text("5.0"))
    yearly_discount_pct = Column(Numeric(5, 2), nullable=False, server_default=text("10.0"))
    price_quarterly_minor = Column(Numeric, nullable=False)
    price_yearly_minor = Column(Numeric, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=func.now())


class Feature(Base):
    """Feature model - defines available system features"""
    __tablename__ = "features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    cluster = Column(String(50), nullable=True)
    usage_type = Column(String(50), nullable=False, default="count")  # count, boolean, storage, api_calls
    max_unit = Column(String(50), nullable=True)  # reports, users, GB, requests
    reset_period = Column(String(20), nullable=False, default="monthly")  # daily, weekly, monthly, yearly
    
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, default=True, nullable=False, index=True)  # legacy — use status instead
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanFeature(Base):
    """Plan-Feature mapping - with validated limits"""
    __tablename__ = "plan_features"
    
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code", ondelete="CASCADE"), nullable=False, index=True)
    feature_code = Column(String(50), ForeignKey("features.code", ondelete="CASCADE"), nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    # Optional limits per plan/feature (e.g., {"max_value": 5, "warn_at": 4})
    limits = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TenantSubscription(Base):
    """Tenant subscription model - tracks tenant plan subscriptions"""
    __tablename__ = "tenant_subscriptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    previous_sub_id = Column(Integer, ForeignKey("tenant_subscriptions.id"), nullable=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code"), nullable=False)
    billing_cycle = Column(String(50), nullable=False, default="monthly")  # standard, trial, promotional
    payment_method = Column(String(20), default="card")  # stripe, card, trade, etc.
    external_id = Column(String(100), index=True, nullable=True)  # External payment provider ID
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_trial = Column(Boolean, default=False, nullable=False)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SubscriptionUsage(Base):
    """Subscription usage tracking - monitors feature usage by tenant"""
    __tablename__ = "subscription_usage"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    feature_code = Column(String(50), ForeignKey("features.code"), nullable=False, index=True)
    usage_type = Column(String(50), nullable=False, index=True)
    usage_count = Column(Integer, default=0, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Composite index for efficient usage lookups
    __table_args__ = (
        Index('ix_subscription_usage_composite', 'tenant_id', 'feature_code', 'period_start'),
    )


class StoreProduct(Base):
    """Store-specific product selection and pricing"""
    __tablename__ = "store_products"
    
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(SQLUUID(as_uuid=True), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(SQLUUID(as_uuid=True), ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Store-specific pricing and availability
    price_minor = Column(Integer, nullable=False)  # Store-specific selling price
    currency = Column(String(3), default="GBP", nullable=False)
    is_available = Column(Boolean, default=True, nullable=False, index=True)
    
    # Store-level inventory tracking
    stock_quantity = Column(Integer, default=0, nullable=False)
    low_stock_threshold = Column(Integer, default=10, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('ix_store_product_unique', 'store_id', 'product_id', unique=True),
    )


class Category(Base):
    """Product category model"""
    __tablename__ = "categories"
    category_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(100), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    parent_category_id = Column(SQLUUID(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, default=True, nullable=False, index=True)  # legacy — use status instead
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"

    # Primary key and identity
    product_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    external_id = Column(String(100), nullable=True, index=True)  # NetSuite/external system ID
    aifi_product_id = Column(String(64), nullable=True, index=True)  # Legacy integration ID
    sku = Column(String(100), nullable=False)  # Stock Keeping Unit
    ean = Column(String(128), nullable=True, index=True)  # European Article Number / barcode
    mpn = Column(String(100), nullable=True)  # Manufacturer Part Number

    # Relationships
    vendor_id = Column(SQLUUID(as_uuid=True), ForeignKey("vendors.vendor_id", ondelete="SET NULL"), nullable=True, index=True)
    category_id = Column(SQLUUID(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True, index=True)
    brand_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)  # FK → brands
    manufacturer = Column(String(255), nullable=True)  # Manufacturer name (free text)

    # Matrix (variant) fields
    is_matrix_item = Column(Boolean, nullable=False, default=False)  # TRUE if product has colour/size/fit variants
    matrix_type = Column(String(20), nullable=False, server_default=text("'standalone'"))  # standalone / parent / child
    matrix_parent_id = Column(SQLUUID(as_uuid=True), ForeignKey("products.product_id", ondelete="SET NULL"), nullable=True, index=True)  # Self-ref for children
    colour_id = Column(SQLUUID(as_uuid=True), ForeignKey("colours.colour_id", ondelete="SET NULL"), nullable=True, index=True)  # FK → colours
    size_id = Column(SQLUUID(as_uuid=True), ForeignKey("sizes.size_id", ondelete="SET NULL"), nullable=True, index=True)  # FK → sizes
    fit_id = Column(SQLUUID(as_uuid=True), ForeignKey("fits.fit_id", ondelete="SET NULL"), nullable=True, index=True)  # FK → fits
    item_option = Column(String(255), nullable=True)  # Domain-specific option (Glove Type, etc.)

    # Description fields
    display_name = Column(String(255), nullable=False)  # Primary display name in UI
    web_display_name = Column(String(255), nullable=True)  # E-commerce display name (max 60 char)
    sales_description = Column(Text, nullable=True)  # Customer-facing description
    purchase_description = Column(Text, nullable=True)  # Supplier-facing description
    packing_slip_description = Column(Text, nullable=True)  # Logistics/packing slip text
    detailed_description = Column(Text, nullable=True)  # Extended/HTML product description
    additional_description = Column(Text, nullable=True)  # Supplementary information

    # Physical attributes
    weight = Column(Numeric(10, 3), nullable=True)  # Product weight value
    weight_unit = Column(String(10), nullable=True)  # g / kg / lb
    width = Column(Numeric(10, 3), nullable=True)  # Width in mm
    depth = Column(Numeric(10, 3), nullable=True)  # Depth in mm
    height = Column(Numeric(10, 3), nullable=True)  # Height in mm

    # Packaging
    outer_quantity = Column(Integer, nullable=True)  # Quantity in outer packaging
    outer_label_id = Column(Integer, ForeignKey("uos_labels.label_id", ondelete="SET NULL"), nullable=True)  # FK → uos_labels
    inner_quantity = Column(Integer, nullable=True)  # Quantity in inner packaging
    inner_label_id = Column(Integer, ForeignKey("uos_labels.label_id", ondelete="SET NULL"), nullable=True)  # FK → uos_labels
    reorder_multiple = Column(Integer, nullable=True)  # Minimum reorder multiple

    # Pricing
    purchase_price_minor = Column(Integer, nullable=False)  # Cost price in pence/cents (minor units)
    currency = Column(String(3), nullable=False, server_default=text("'GBP'"))
    tax_rate = Column(BigInteger, nullable=False, server_default=text("0"))

    # Classification
    manufacturer_country = Column(String(100), nullable=True)  # Country of origin
    commodity_code = Column(String(50), nullable=True)  # HS/customs commodity code
    product_type = Column(String(50), nullable=True)  # Product type classification

    # Web / filtering
    colour_filter = Column(String(100), nullable=True)  # Filterable colour value for web store
    size_filter = Column(String(100), nullable=True)  # Filterable size value for web store
    search_keywords = Column(Text, nullable=True)  # SEO / site search keywords

    # Hazmat fields
    is_dangerous_goods = Column(Boolean, nullable=False, default=False)  # Master dangerous goods flag
    cas_number = Column(String(50), nullable=True)  # Chemical Abstracts Service number
    un_number = Column(String(50), nullable=True)  # UN dangerous goods number
    proper_shipping_name = Column(String(255), nullable=True)  # Official shipping name for hazmat
    transport_hazard_class = Column(String(50), nullable=True)  # Hazmat transport class
    packing_group = Column(String(20), nullable=True)  # I / II / III
    adr_classification_code = Column(String(50), nullable=True)  # ADR road transport classification
    adr_tunnel_restriction_code = Column(String(20), nullable=True)  # Tunnel restriction code
    adr_hazard_id_number = Column(String(50), nullable=True)  # ADR hazard identification number

    # System fields
    tax_code = Column(String(64), nullable=True)  # Tax code reference
    restricted = Column(Boolean, nullable=False, default=False, index=True)  # Restricted product flag
    product_metadata = Column(JSONB, nullable=True)  # Flexible JSON for extra data
    comments = Column(Text, nullable=True)  # Free-text notes/comments
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete timestamp
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=func.now(), nullable=True)

    __table_args__ = (
        Index("ix_products_tenant_sku_unique", "tenant_id", "sku", unique=True),
        Index("ix_products_tenant_ean_unique", "tenant_id", "ean", unique=True, postgresql_where=text("ean IS NOT NULL")),
    )


class ProductImage(Base):
    """Product image model - multiple images per product"""
    __tablename__ = "product_images"

    image_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(SQLUUID(as_uuid=True), ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String(500), nullable=False)  # URL to image file
    position = Column(Integer, nullable=False, default=1)  # Display order (1-5)
    is_primary = Column(Boolean, nullable=False, default=False)  # Primary/thumbnail image flag
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Variant(Base):
    """Product variant model - SKU variations (size, color, etc.)"""
    __tablename__ = "variants"
    variant_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(SQLUUID(as_uuid=True), ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    attributes = Column(JSONB, nullable=True)  # e.g., {"size": "L", "color": "red"}
    price_minor = Column(Integer, nullable=False)
    currency = Column(String(3), default="GBP", nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)
    low_stock_threshold = Column(Integer, default=10, nullable=False)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, default=True, nullable=False, index=True)  # legacy — use status instead
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SpendingEvent(Base):
    """Spending events for budget tracking and audit"""
    __tablename__ = "spending_events"
    
    event_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(50), nullable=False)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id"), nullable=False, index=True)
    order_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency_code = Column(String(3), default="GBP")
    event_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Add relationships
User.cost_centres = relationship("UserCostCentre", back_populates="user")
CostCentre.members = relationship("UserCostCentre", back_populates="cost_centre")


class SiteTenant(Base):
    """Junction table for many-to-many relationship between sites and tenants"""
    __tablename__ = "site_tenants"
    
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(SQLUUID(as_uuid=True), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Add unique constraint to prevent duplicates
    __table_args__ = (
        Index('ix_site_tenant_unique', 'site_id', 'tenant_id', unique=True),
    )


class VendorUser(Base):
    """Vendor-specific user accounts"""
    __tablename__ = "vendor_users"

    user_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(SQLUUID(as_uuid=True), ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False, index=True)

    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="vendor_staff")  # vendor_admin / vendor_staff
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted
    active = Column(Boolean, nullable=False, default=True, index=True)  # legacy — use status instead

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_vendor_users_vendor_email_unique', 'vendor_id', 'email', unique=True),
    )


# ==================================================================================
# CARRIER & GOVERNANCE MODELS
# ==================================================================================

class Carrier(Base):
    """Carrier / logistics provider — global entity"""
    __tablename__ = "carriers"

    carrier_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, index=True)
    code = Column(String(50), nullable=True, unique=True, index=True)
    carrier_type = Column(String(50), nullable=True)  # parcel / freight / courier / marketplace
    tracking_url_template = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TenantCarrier(Base):
    """Tenant ↔ Carrier mapping (ALLOWS_CARRIER edge in graph)"""
    __tablename__ = "tenant_carriers"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    carrier_id = Column(SQLUUID(as_uuid=True), ForeignKey("carriers.carrier_id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=False, default="approved")  # preferred / approved / blocked
    integration_type = Column(String(50), nullable=True)  # api / edi / email / marketplace / manual
    account_number = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_tenant_carrier_unique', 'tenant_id', 'carrier_id', unique=True),
    )


class UserApprover(Base):
    """User ↔ CostCentre approval mapping (IS_APPROVER_FOR edge in graph)"""
    __tablename__ = "user_approvers"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"), nullable=False, index=True)
    approval_limit_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default="GBP")
    rule_set_id = Column(SQLUUID(as_uuid=True), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_user_approver_unique', 'user_id', 'cost_centre_id', unique=True),
    )


# ==================================================================================
# APPROVED RANGE MODELS
# ==================================================================================

class ApprovedRange(Base):
    """A curated basket of products, controlled by tenant admin, scoped to org units"""
    __tablename__ = "approved_ranges"

    approved_range_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_universal = Column(Boolean, nullable=False, default=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active / inactive / deleted

    created_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_approved_range_tenant_name', 'tenant_id', 'name', unique=True),
    )


class ApprovedRangeOrgUnit(Base):
    """Maps an approved range to an org unit (many-to-many)"""
    __tablename__ = "approved_range_org_units"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approved_range_id = Column(SQLUUID(as_uuid=True), ForeignKey("approved_ranges.approved_range_id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_ar_org_unit_unique', 'approved_range_id', 'org_unit_id', unique=True),
    )


class ApprovedRangeProduct(Base):
    """Maps a product into an approved range (many-to-many)"""
    __tablename__ = "approved_range_products"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approved_range_id = Column(SQLUUID(as_uuid=True), ForeignKey("approved_ranges.approved_range_id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(SQLUUID(as_uuid=True), ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False, index=True)
    added_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_ar_product_unique', 'approved_range_id', 'product_id', unique=True),
    )


# ==================================================================================
# OUTBOX & AUDIT MODELS
# ==================================================================================

class OutboxEvent(Base):
    __tablename__ = 'outbox_events'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='pending', nullable=False, index=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(default=3, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_outbox_relay_poll', 'processed_at', 'created_at',
              postgresql_nulls_not_distinct=False),
        Index('ix_outbox_aggregate', 'aggregate_type', 'aggregate_id', 'created_at'),
    )


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(nullable=False)
    resource_type: Mapped[str] = mapped_column(nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
