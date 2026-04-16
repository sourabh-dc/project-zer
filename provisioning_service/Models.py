from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, func, UUID, BigInteger, text, Text, JSON, \
    Date, Numeric, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base, relationship, backref, Mapped, mapped_column, synonym
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
    active = Column(Boolean, nullable=False, default=True, index=True)

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
    active = Column(Boolean, nullable=False, default=True, index=True)

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
    active = Column(Boolean, nullable=False, default=True, index=True)

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
    is_active = Column(Boolean, nullable=False, default=True, index=True)

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
    status = Column(String, nullable=False, index=True)  # active/archived

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
    status = Column(String(50), default="active", index=True)
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
    active = Column(Boolean, nullable=False, default=True, index=True)

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
    gl_code = Column(String(100), nullable=True, index=True)          # General Ledger code
    owner_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)

    # New budget control columns
    period_granularity = Column(String(20), nullable=True, default="month")  # week|month|quarter|year
    carry_forward_enabled = Column(Boolean, nullable=False, default=False)
    default_calendar_id = Column(SQLUUID(as_uuid=True), ForeignKey("financial_calendars.calendar_id", ondelete="SET NULL"), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)

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
    
    active = Column(Boolean, default=True, nullable=False, index=True)
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
    status = Column(String(20), default="active")  # active, trialing, past_due, canceled, unpaid

    # Grace period & payment failure tracking
    payment_failed_at = Column(DateTime(timezone=True), nullable=True)
    grace_period_end = Column(DateTime(timezone=True), nullable=True)
    last_invoice_id = Column(String(100), nullable=True)  # Stripe invoice ID


class Mandate(Base):
    """
    Billing mandate — created BEFORE any tenant/user data is persisted.

    A mandate captures the billing intent (plan, trial flag, Stripe customer)
    and acts as the gate: tenant + admin user are only created once the
    mandate reaches status='active' (payment confirmed or trial started).

    Lifecycle:
      1. POST /onboarding/mandate     -> status='pending'  (Stripe customer + SetupIntent created)
      2. POST /onboarding/activate    -> status='active'    (payment confirmed or trial started)
      3. Webhook subscription.deleted -> status='expired'   (trial/subscription ended)
      4. Manual cancel                -> status='cancelled'
    """
    __tablename__ = "mandates"

    mandate_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False, index=True)
    tenant_name = Column(String(200), nullable=False)
    tenant_type = Column(String(50), nullable=False, default="retailer")

    # Admin details (held until activation)
    admin_email = Column(String, nullable=False)
    admin_firstname = Column(String(150), nullable=False)
    admin_lastname = Column(String(150), nullable=False)
    password_hash = Column(String, nullable=False)

    # Billing
    plan_code = Column(String(50), nullable=False)
    billing_cycle = Column(String(20), nullable=False, default="monthly")
    is_trial = Column(Boolean, nullable=False, default=True)
    trial_days = Column(Integer, nullable=False, default=7)
    stripe_customer_id = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)
    stripe_setup_intent_secret = Column(String(255), nullable=True)

    # State
    status = Column(String(20), nullable=False, default="pending")  # pending, active, expired, cancelled
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=True)  # set once tenant is created on activation

    # Extra onboarding fields (carried forward to Tenant)
    phone = Column(String, nullable=True)
    default_currency = Column(String(3), nullable=True, default="GBP")
    timezone = Column(String, nullable=True, default="UTC")
    locale = Column(String, nullable=True, default="en_GB")
    industry = Column(String, nullable=True)
    registration_number = Column(String(100), nullable=True)
    billing_address = Column(JSONB, nullable=True)
    primary_domain = Column(String, nullable=True)
    billing_email = Column(String, nullable=True)
    tech_contact_email = Column(String, nullable=True)
    support_contact_email = Column(String, nullable=True)
    extra_data = Column("metadata", JSONB, nullable=True)  # freeform extra data

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


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
    active = Column(Boolean, default=True, nullable=False, index=True)
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
    active = Column(Boolean, nullable=False, default=True, index=True)  # Active/inactive flag
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
    active = Column(Boolean, default=True, nullable=False, index=True)
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
    active = Column(Boolean, nullable=False, default=True, index=True)

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
# FINANCIAL CALENDAR MODELS
# ==================================================================================

class FinancialCalendar(Base):
    """
    Tenant-defined financial calendar.  A tenant may have multiple simultaneous
    calendars (e.g. corporate Gregorian + project 4-4-5).
    """
    __tablename__ = "financial_calendars"

    calendar_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id   = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # gregorian | 445 | 454 | 444 | custom
    calendar_type = Column(String(20), nullable=False, default="gregorian", index=True)
    start_month   = Column(Integer, nullable=False, default=1)   # 1=January … 12=December
    currency      = Column(String(3), nullable=True, default="GBP")
    is_active     = Column(Boolean, nullable=False, default=True, index=True)
    is_default    = Column(Boolean, nullable=False, default=False)

    created_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_financial_calendar_tenant_name", "tenant_id", "name", unique=True),
    )


class FinancialYear(Base):
    """
    A financial year (full, part, or adjusted) belonging to a calendar.
    Part-years are allowed on onboarding or during calendar adjustments.
    """
    __tablename__ = "financial_years"

    year_id     = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calendar_id = Column(SQLUUID(as_uuid=True), ForeignKey("financial_calendars.calendar_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    tenant_id   = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    label      = Column(String(50), nullable=False)          # e.g. "FY2025", "FY2025-Part1"
    start_date = Column(Date, nullable=False)
    end_date   = Column(Date, nullable=False)
    # full | part | adjusted
    year_type  = Column(String(20), nullable=False, default="full")
    # draft | active | closed
    status     = Column(String(20), nullable=False, default="draft", index=True)

    total_budget_minor    = Column(BigInteger, nullable=True)   # company-level cap for this year
    notes                 = Column(Text, nullable=True)

    created_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    calendar = relationship("FinancialCalendar", backref="years", foreign_keys=[calendar_id])

    __table_args__ = (
        Index("ix_financial_year_tenant_label", "tenant_id", "label", unique=True),
    )


class FinancialPeriod(Base):
    """
    A single period (week, month, quarter) within a financial year.
    Rows are auto-generated by the period_calculator for standard calendar types,
    or manually created for custom calendars.
    """
    __tablename__ = "financial_periods"

    period_id     = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year_id       = Column(SQLUUID(as_uuid=True), ForeignKey("financial_years.year_id", ondelete="CASCADE"),
                           nullable=False, index=True)
    calendar_id   = Column(SQLUUID(as_uuid=True), ForeignKey("financial_calendars.calendar_id", ondelete="CASCADE"),
                           nullable=False, index=True)
    tenant_id     = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                           nullable=False, index=True)
    period_number = Column(Integer, nullable=False)          # sequential within the year
    label         = Column(String(50), nullable=False)       # e.g. "P1", "Q1", "W01"
    # week | month | quarter
    period_type   = Column(String(20), nullable=False, default="month")
    start_date    = Column(Date, nullable=False)
    end_date      = Column(Date, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    year = relationship("FinancialYear", backref="periods", foreign_keys=[year_id])

    __table_args__ = (
        Index("ix_fin_period_year_num", "year_id", "period_number", unique=True),
    )


# ==================================================================================
# COMPANY BUDGET CAP
# ==================================================================================

class CompanyBudgetCap(Base):
    """
    Top-level company-wide budget cap for a financial year.
    Soft enforcement: admins may override with a recorded reason.
    """
    __tablename__ = "company_budget_caps"

    cap_id     = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id  = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                        nullable=False, index=True)
    year_id    = Column(SQLUUID(as_uuid=True), ForeignKey("financial_years.year_id", ondelete="CASCADE"),
                        nullable=False, index=True)
    calendar_id = Column(SQLUUID(as_uuid=True), ForeignKey("financial_calendars.calendar_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    currency           = Column(String(3), nullable=False, default="GBP")
    total_budget_minor = Column(BigInteger, nullable=False)
    allocated_minor    = Column(BigInteger, nullable=False, default=0)
    committed_minor    = Column(BigInteger, nullable=False, default=0)
    spent_minor        = Column(BigInteger, nullable=False, default=0)
    # If True, exceeding the cap blocks save; if False it warns but allows with reason
    hard_cap           = Column(Boolean, nullable=False, default=False)
    notes              = Column(Text, nullable=True)

    created_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_company_cap_tenant_year", "tenant_id", "year_id", unique=True),
    )


# ==================================================================================
# COST CENTRE BUDGET VERSIONS  (replaces CostCenterBudget)
# ==================================================================================

class CostCentreBudgetVersion(Base):
    """
    Versioned budget allocation for a cost centre, scoped to a financial year
    and optionally a specific period.  period_id=NULL means an annual lump-sum.

    Supports:
    - Carry-forward: carry_forward_minor is added to the next period's opening balance.
    - Mixed granularity: a CC may have some annual and some monthly entries.
    """
    __tablename__ = "cc_budget_versions"

    version_id     = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    year_id        = Column(SQLUUID(as_uuid=True), ForeignKey("financial_years.year_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    period_id      = Column(SQLUUID(as_uuid=True), ForeignKey("financial_periods.period_id", ondelete="SET NULL"),
                            nullable=True, index=True)  # NULL → annual allocation
    tenant_id      = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    currency       = Column(String(3), nullable=False, default="GBP")

    # Monetary buckets (minor units)
    budget_minor         = Column(BigInteger, nullable=False)
    carry_forward_minor  = Column(BigInteger, nullable=False, default=0)
    allocated_to_users_minor = Column(BigInteger, nullable=False, default=0)
    committed_minor      = Column(BigInteger, nullable=False, default=0)
    spent_minor          = Column(BigInteger, nullable=False, default=0)

    # draft | active | closed
    status         = Column(String(20), nullable=False, default="draft", index=True)
    override_reason = Column(Text, nullable=True)   # populated when company cap is breached

    closed_at  = Column(DateTime(timezone=True), nullable=True)
    closed_by  = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    cost_centre = relationship("CostCentre", backref="budget_versions", foreign_keys=[cost_centre_id])
    year        = relationship("FinancialYear", backref="cc_budget_versions", foreign_keys=[year_id])


class BudgetTransaction(Base):
    """
    Immutable double-entry ledger recording every change to any budget bucket.
    Used for full audit trail and cross-CC reallocation.
    """
    __tablename__ = "budget_transactions"

    txn_id        = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id     = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # allocation | reallocation_debit | reallocation_credit |
    # bring_forward | top_up | commitment | spend | reversal | carry_forward
    txn_type      = Column(String(50), nullable=False, index=True)
    source_version_id = Column(SQLUUID(as_uuid=True), ForeignKey("cc_budget_versions.version_id", ondelete="SET NULL"),
                               nullable=True, index=True)
    target_version_id = Column(SQLUUID(as_uuid=True), ForeignKey("cc_budget_versions.version_id", ondelete="SET NULL"),
                               nullable=True, index=True)
    amount_minor  = Column(BigInteger, nullable=False)
    currency      = Column(String(3), nullable=False, default="GBP")
    reference_id  = Column(SQLUUID(as_uuid=True), nullable=True, index=True)  # FK to request/approval
    note          = Column(Text, nullable=True)

    performed_by  = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ==================================================================================
# USER BUDGET ALLOCATION  (replaces UserCostCentre for new tenants)
# ==================================================================================

class UserCostCentreAssignment(Base):
    """
    Links a user to a cost centre.  A user may belong to multiple cost centres.
    """
    __tablename__ = "user_cc_assignments"

    assignment_id  = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    tenant_id      = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    is_primary     = Column(Boolean, nullable=False, default=False)
    is_active      = Column(Boolean, nullable=False, default=True)
    effective_from = Column(Date, nullable=True)
    effective_to   = Column(Date, nullable=True)

    assigned_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_user_cc_assign_unique", "user_id", "cost_centre_id", unique=True),
    )


class UserBudgetLimit(Base):
    """
    Per-user, per-cost-centre, per-year budget/approval limit for a specific
    time-window.  A user may have multiple rows (e.g. one for transaction + one
    for monthly + one for annual).

    limit_type:
        requester – controls whether order routes for approval (routing constraint)
        approver  – signing authority; deducted at commitment (binding control)

    window_type:
        transaction | week | month | quarter | year
    """
    __tablename__ = "user_budget_limits"

    limit_id       = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    year_id        = Column(SQLUUID(as_uuid=True), ForeignKey("financial_years.year_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    period_id      = Column(SQLUUID(as_uuid=True), ForeignKey("financial_periods.period_id", ondelete="SET NULL"),
                            nullable=True, index=True)   # NULL → applies to the whole year
    tenant_id      = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    currency       = Column(String(3), nullable=False, default="GBP")

    # requester | approver
    limit_type   = Column(String(20), nullable=False, index=True)
    # transaction | week | month | quarter | year
    window_type  = Column(String(20), nullable=False, index=True)

    limit_amount_minor = Column(BigInteger, nullable=False)   # 0 = always routes for approval
    committed_minor    = Column(BigInteger, nullable=False, default=0)
    spent_minor        = Column(BigInteger, nullable=False, default=0)
    carry_forward_minor = Column(BigInteger, nullable=False, default=0)
    carry_forward_enabled = Column(Boolean, nullable=False, default=False)

    # Window reset tracking
    window_start = Column(Date, nullable=True)
    window_end   = Column(Date, nullable=True)
    next_reset_date = Column(Date, nullable=True)

    is_active   = Column(Boolean, nullable=False, default=True)
    created_by  = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_user_limit_unique", "user_id", "cost_centre_id", "year_id", "limit_type", "window_type", unique=True),
    )


# ==================================================================================
# APPROVAL ROUTING ENGINE
# ==================================================================================

class ApprovalPolicy(Base):
    """
    Tenant-level (or cost-centre-level) approval routing policy.
    Defines the overall routing mode and SOX/SoD settings.
    """
    __tablename__ = "approval_policies"

    policy_id   = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id   = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"),
                            nullable=True, index=True)  # NULL = tenant-wide policy
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # broadcast | hierarchical
    routing_mode      = Column(String(20), nullable=False, default="hierarchical")
    # For broadcast: how many approvers to notify concurrently
    broadcast_n       = Column(Integer, nullable=False, default=3)
    # Segregation of Duties: requester cannot approve their own order
    sox_sod_enforced  = Column(Boolean, nullable=False, default=True)
    # block | partial | force_top_up
    partial_approval_mode = Column(String(20), nullable=False, default="block")
    # auto | require_approval
    zero_value_mode   = Column(String(20), nullable=False, default="auto")

    is_active   = Column(Boolean, nullable=False, default=True, index=True)
    created_by  = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    stages = relationship("ApprovalStage", back_populates="policy",
                          order_by="ApprovalStage.stage_order", cascade="all, delete-orphan")


class ApprovalStage(Base):
    """
    One stage in an N-level approval chain.
    Stages are evaluated in order; each stage can run sequentially or in parallel
    with others (parallel_allowed).  min_approvers controls how many concurrent
    approvers must approve before the stage is marked complete.
    """
    __tablename__ = "approval_stages"

    stage_id      = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id     = Column(SQLUUID(as_uuid=True), ForeignKey("approval_policies.policy_id", ondelete="CASCADE"),
                           nullable=False, index=True)
    stage_order   = Column(Integer, nullable=False)          # 1, 2, 3 …
    name          = Column(String(255), nullable=True)       # e.g. "Line Manager", "Finance Director"
    parallel_allowed = Column(Boolean, nullable=False, default=False)
    min_approvers    = Column(Integer, nullable=False, default=1)  # approvals needed to pass stage
    escalation_timeout_hours = Column(Integer, nullable=True)      # NULL = no timeout

    policy = relationship("ApprovalPolicy", back_populates="stages")
    conditions = relationship("ApprovalStageCondition", back_populates="stage",
                              cascade="all, delete-orphan")
    approvers  = relationship("ApprovalStageApprover", back_populates="stage",
                              cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_approval_stage_policy_order", "policy_id", "stage_order", unique=True),
    )


class ApprovalStageCondition(Base):
    """
    Condition that must be satisfied for a stage to be active.
    Multiple conditions on the same stage are combined with the specified logic.

    field:    amount | cost_centre | category | vendor | period_type
    operator: gte | lte | eq | in | neq
    value:    JSONB (scalar or list)
    logic:    AND | OR (how this condition combines with others on the same stage)
    """
    __tablename__ = "approval_stage_conditions"

    condition_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_id     = Column(SQLUUID(as_uuid=True), ForeignKey("approval_stages.stage_id", ondelete="CASCADE"),
                          nullable=False, index=True)
    field        = Column(String(50), nullable=False)
    operator     = Column(String(10), nullable=False)
    value        = Column(JSONB, nullable=False)
    logic        = Column(String(5), nullable=False, default="AND")  # AND | OR

    stage = relationship("ApprovalStage", back_populates="conditions")


class ApprovalStageApprover(Base):
    """
    Defines who can approve at a given stage.
    approver_type:
        user               – specific user
        org_unit_manager   – manager of the requester's org unit
        hierarchy_traversal – walk OrgUnit tree using manager_user_id chain
        role               – any user holding a specific role in the cost centre
    """
    __tablename__ = "approval_stage_approvers"

    id               = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_id         = Column(SQLUUID(as_uuid=True), ForeignKey("approval_stages.stage_id", ondelete="CASCADE"),
                              nullable=False, index=True)
    approver_type    = Column(String(30), nullable=False)
    approver_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    org_unit_id      = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="SET NULL"), nullable=True)
    role_code        = Column(String(100), nullable=True)

    stage = relationship("ApprovalStage", back_populates="approvers")


# ==================================================================================
# PURCHASE REQUEST & WORKFLOW
# ==================================================================================

class PurchaseRequest(Base):
    """
    Central entity for an indirect goods purchase request raised by a user.
    """
    __tablename__ = "purchase_requests"

    request_id     = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    requester_id   = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    vendor_id      = Column(SQLUUID(as_uuid=True), ForeignKey("vendors.vendor_id", ondelete="SET NULL"),
                            nullable=True, index=True)
    category_id    = Column(SQLUUID(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"),
                            nullable=True, index=True)
    year_id        = Column(SQLUUID(as_uuid=True), ForeignKey("financial_years.year_id", ondelete="SET NULL"),
                            nullable=True, index=True)
    period_id      = Column(SQLUUID(as_uuid=True), ForeignKey("financial_periods.period_id", ondelete="SET NULL"),
                            nullable=True, index=True)

    reference_number = Column(String(50), nullable=True, index=True)  # human-readable PR number
    description      = Column(Text, nullable=True)
    line_items       = Column(JSONB, nullable=True)   # [{product_id, qty, unit_price_minor, ...}]
    amount_minor     = Column(BigInteger, nullable=False)
    currency         = Column(String(3), nullable=False, default="GBP")

    # draft | pending_approval | approved | rejected | cancelled | po_issued
    status = Column(String(30), nullable=False, default="draft", index=True)
    # self_approved | workflow
    approval_mode = Column(String(20), nullable=True)

    notes         = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    approved_by   = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    approved_at   = Column(DateTime(timezone=True), nullable=True)
    po_issued_at  = Column(DateTime(timezone=True), nullable=True)
    po_reference  = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    requester = relationship("User", foreign_keys=[requester_id], backref="purchase_requests")
    workflow  = relationship("ApprovalWorkflow", back_populates="request",
                             uselist=False, cascade="all, delete-orphan")


class ApprovalWorkflow(Base):
    """
    Tracks the active multi-stage approval workflow for a purchase request.
    """
    __tablename__ = "approval_workflows"

    workflow_id         = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id          = Column(SQLUUID(as_uuid=True), ForeignKey("purchase_requests.request_id", ondelete="CASCADE"),
                                 nullable=False, unique=True, index=True)
    policy_id           = Column(SQLUUID(as_uuid=True), ForeignKey("approval_policies.policy_id", ondelete="SET NULL"),
                                 nullable=True)
    tenant_id           = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                                 nullable=False, index=True)
    current_stage_order = Column(Integer, nullable=False, default=1)
    # active | completed | rejected | escalated | cancelled
    status              = Column(String(20), nullable=False, default="active", index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    request = relationship("PurchaseRequest", back_populates="workflow")
    tasks   = relationship("ApprovalTask", back_populates="workflow", cascade="all, delete-orphan")


class ApprovalTask(Base):
    """
    A single approval action assigned to one approver for one stage.
    Escalation is modelled via escalated_to_user_id; if escalation occurs a new
    ApprovalTask row is created for the escalated approver.
    """
    __tablename__ = "approval_tasks"

    task_id      = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id  = Column(SQLUUID(as_uuid=True), ForeignKey("approval_workflows.workflow_id", ondelete="CASCADE"),
                          nullable=False, index=True)
    stage_id     = Column(SQLUUID(as_uuid=True), ForeignKey("approval_stages.stage_id", ondelete="SET NULL"),
                          nullable=True, index=True)
    tenant_id    = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                          nullable=False, index=True)
    assignee_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"),
                               nullable=True, index=True)
    stage_order  = Column(Integer, nullable=False)

    # pending | approved | rejected | escalated | expired | cancelled
    status      = Column(String(20), nullable=False, default="pending", index=True)
    decided_at  = Column(DateTime(timezone=True), nullable=True)
    decided_by  = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    note        = Column(Text, nullable=True)
    escalated_to_task_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_tasks.task_id", ondelete="SET NULL"),
                                   nullable=True)  # points to the new task created on escalation

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workflow = relationship("ApprovalWorkflow", back_populates="tasks")


# ==================================================================================
# BUDGET CHANGE REQUESTS  (top-up / bring-forward / reallocation)
# ==================================================================================

class BudgetChangeRequest(Base):
    """
    Formal request to modify budget mid-period.
    These are themselves routed through the approval engine.

    request_type:
        top_up         – add funds from central pool to a CC version
        bring_forward  – pull future-period budget into current period
        reallocation   – transfer between two CC versions (debit/credit)
    """
    __tablename__ = "budget_change_requests"

    change_req_id  = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    # top_up | bring_forward | reallocation
    request_type   = Column(String(30), nullable=False, index=True)
    requester_id   = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"),
                            nullable=False, index=True)
    # For bring_forward: the future period being pulled from
    from_version_id = Column(SQLUUID(as_uuid=True), ForeignKey("cc_budget_versions.version_id", ondelete="SET NULL"),
                              nullable=True, index=True)
    # The target period/version being credited
    to_version_id   = Column(SQLUUID(as_uuid=True), ForeignKey("cc_budget_versions.version_id", ondelete="SET NULL"),
                              nullable=False, index=True)
    amount_minor    = Column(BigInteger, nullable=False)
    currency        = Column(String(3), nullable=False, default="GBP")
    justification   = Column(Text, nullable=True)

    # pending | approved | rejected | cancelled
    status      = Column(String(20), nullable=False, default="pending", index=True)
    approved_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ==================================================================================
# OUTBOX & AUDIT MODELS
# ==================================================================================

class OutboxEvent(Base):
    __tablename__ = 'outbox_events'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    aggregate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(default='pending')
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class OutboxEventDelivery(Base):
    __tablename__ = 'outbox_event_delivery'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('outbox_events.id'), nullable=False)
    consumer: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending')
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint('event_id', 'consumer', name='uq_delivery_event_consumer'),
        Index('idx_delivery_consumer_status', 'consumer', 'status'),
        Index('idx_delivery_consumer_status_created', 'consumer', 'status', 'created_at'),
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
