from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, func, UUID, BigInteger, text, Text, JSON, \
    Date, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import uuid

from core.db_config import engine
from utils.logger import logger

# ==================================================================================
# DATABASE MODELS
# ==================================================================================
Base = declarative_base()

class Tenant(Base):
    """Tenant organization model"""
    __tablename__ = "tenants"

    tenant_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sites = relationship("Site", secondary="site_tenants", back_populates="tenants")
    tenant_name = Column(String(200), nullable=False, unique=True, index=True)
    tenant_type = Column("tenant_type", String(50), nullable=False)  # customer, retailer, distributor
    registration_number = Column(String(100), nullable=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Site(Base):
    """Site model - physical locations that can be managed by multiple tenants"""
    __tablename__ = "sites"
    site_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    site_type = Column(String(50), nullable=False)
    geo = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    tenants = relationship("Tenant", secondary="site_tenants", back_populates="sites")

class Store(Base):
    """Store model - retail locations under a site"""
    __tablename__ = "stores"
    store_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(SQLUUID(as_uuid=True), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    store_type = Column(String(50), nullable=False)
    geo = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    user_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    aifi_customer_id = Column(String(64), nullable=True, index=True)
    email = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    user_metadata = Column(JSONB, nullable=True)
    password = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    refresh_token = Column(String(255), nullable=True)
    refresh_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_logout_at = Column(DateTime(timezone=True), nullable=True)
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow, nullable=True)

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


class RoleScope(Base):
    """Role scope mapping for fine-grained access control"""
    __tablename__ = "role_scopes"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(SQLUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)  # tenant, site, store, cost_centre, user, org_unit
    resource_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)
    grant_type = Column(String(20), nullable=False, default="include")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OrgUnit(Base):
    """Organisational hierarchy unit"""
    __tablename__ = "org_units"
    org_unit_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)  # directorate, business_unit, cost_centre, etc.
    name = Column(String(255), nullable=False)
    parent_org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class UserOrgAssignment(Base):
    """User assignment into organisational hierarchy"""
    __tablename__ = "user_org_assignments"
    assignment_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(SQLUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())


class ApprovalDelegation(Base):
    """Delegated approval assignments"""
    __tablename__ = "approval_delegations"
    delegation_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delegator_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    delegate_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True, index=True)
    resource_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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


class CostCentre(Base):
    """Cost Centre model - budget tracking"""
    __tablename__ = "cost_centres"
    cost_centre_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    manager_user_id = Column(SQLUUID(as_uuid=True), nullable=True)  # Optional manager
    budget_minor = Column(BigInteger, default=0)  # Amount in minor units (pence/cents)
    spent_minor = Column(BigInteger, default=0)
    currency_code = Column(String(3), default="GBP")
    status = Column(String(50), default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class UserCostCentre(Base):
    __tablename__ = "user_cost_centres"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id"), nullable=False, index=True)
    allocated_budget_minor = Column(BigInteger, nullable=False, default=0)
    spent_minor = Column(BigInteger, nullable=False, default=0)
    currency_code = Column(String(3), default="GBP")
    recurring_budget_minor = Column(BigInteger, default=0)  # Auto-allocated amount
    recurring_period = Column(String(20), default="none")  # none, daily, weekly, monthly, yearly
    last_reset_date = Column(Date, nullable=True)
    next_reset_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    user = relationship("User", back_populates="cost_centres")
    cost_centre = relationship("CostCentre", back_populates="members")

class SubscriptionPlan(Base):
    """Subscription plan - TODO: migrate to UUID for consistency"""
    __tablename__ = "subscription_plans"
    plan_id = Column(SQLUUID(as_uuid=True), primary_key=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow)

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
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow)

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


class SiteBillingAccount(Base):
    """Site billing account model - payment details for sites"""
    __tablename__ = "site_billing_accounts"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), index=True, nullable=False)
    site_id = Column(SQLUUID(as_uuid=True), ForeignKey("sites.site_id", ondelete="CASCADE"), index=True, nullable=False)
    payment_method = Column(String(20), nullable=False)
    external_id = Column(String(100), index=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    account_metadata = Column(JSONB, nullable=True)
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


class StoreVariant(Base):
    """Store-specific variant overrides for products"""
    __tablename__ = "store_variants"
    
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_product_id = Column(SQLUUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(SQLUUID(as_uuid=True), ForeignKey("variants.variant_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Optional variant-level overrides
    price_minor = Column(Integer, nullable=True)  # If null, use StoreProduct price
    stock_quantity = Column(Integer, nullable=True)  # Track variant stock per store
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('ix_store_variant_unique', 'store_product_id', 'variant_id', unique=True),
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

    product_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    aifi_product_id = Column(String(64), nullable=True, index=True)
    vendor_id = Column(SQLUUID(as_uuid=True), ForeignKey("vendors.vendor_id", ondelete="SET NULL"), nullable=True, index=True)
    category_id = Column(SQLUUID(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True, index=True)
    sku = Column(String(100), nullable=False)
    barcode = Column(String(128), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    brand = Column(String(100), nullable=True)
    manufacturer = Column(String(255), nullable=True)
    base_price_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, server_default=text("'GBP'"))
    weight = Column(Numeric(10, 3), nullable=True)  # Kg or grams; stored as decimal
    tax_rate = Column(BigInteger, nullable=False, server_default="0")
    tax_code = Column(String(64), nullable=True)
    product_type = Column(String(50), nullable=True)
    restricted = Column(Boolean, nullable=False, default=False, index=True)
    thumbnail = Column(String(500), nullable=True)
    invalid_thumbnail = Column(Boolean, default=False, nullable=False)
    product_metadata = Column(JSONB, nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow, nullable=True)

    __table_args__ = (
        Index("ix_products_tenant_sku_unique", "tenant_id", "sku", unique=True),
        Index("ix_products_tenant_barcode_unique", "tenant_id", "barcode", unique=True),
    )



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


class Pricebook(Base):
    """Pricebook model - store-specific pricing catalogs"""
    __tablename__ = "pricebooks"
    pricebook_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(SQLUUID(as_uuid=True), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    currency = Column(String(3), default="GBP", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PriceRule(Base):
    """Price rule model - pricing rules for products in pricebooks"""
    __tablename__ = "price_rules"
    rule_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pricebook_id = Column(SQLUUID(as_uuid=True), ForeignKey("pricebooks.pricebook_id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(SQLUUID(as_uuid=True), ForeignKey("products.product_id", ondelete="CASCADE"), nullable=True, index=True)
    variant_id = Column(SQLUUID(as_uuid=True), ForeignKey("variants.variant_id", ondelete="CASCADE"), nullable=True, index=True)
    rule_type = Column(String(50), nullable=False)  # fixed, percentage, discount
    rule_value = Column(Integer, nullable=False)  # For fixed: price in minor units, for percentage: basis points (e.g., 1000 = 10%)
    min_quantity = Column(Integer, nullable=True)
    max_quantity = Column(Integer, nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ApprovalChain(Base):
    """Approval chain model - workflow templates for approval processes"""
    __tablename__ = "approval_chains"
    chain_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    chain_type = Column(String(50), nullable=False, index=True)  # budget, purchase_order, vendor_onboarding
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ApprovalChainStep(Base):
    """Approval chain step model - individual steps in an approval chain"""
    __tablename__ = "approval_chain_steps"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_chain_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_chains.chain_id", ondelete="CASCADE"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    approver_role = Column(String(100), nullable=False)  # manager, finance_controller, director
    approver_scope = Column(String(50), nullable=False)  # site, tenant, store
    escalation_after_hours = Column(Integer, nullable=True)
    is_required = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ApprovalRequest(Base):
    """Approval request model - individual approval requests"""
    __tablename__ = "approval_requests"
    request_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="SET NULL"), nullable=True, index=True)
    chain_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_chains.chain_id"), nullable=False, index=True)
    request_number = Column(String(50), nullable=False, unique=True, index=True)
    request_type = Column(String(50), nullable=False, index=True)  # budget, order, vendor, approval_limit_increase, cost_centre_increase
    request_data = Column(JSONB, nullable=False)
    requested_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    request_status = Column(String(20), default="pending", nullable=False, index=True)  # pending, partially_approved, approved, rejected, closed, expired, escalated
    current_step_number = Column(Integer, default=1, nullable=False)
    total_amount_minor = Column(Integer, nullable=True)
    remaining_amount_minor = Column(Integer, nullable=True)
    currency = Column(String(3), default="GBP", nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    completed_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ApprovalRequestApprover(Base):
    """Approval request approver model - tracks individual approver responses"""
    __tablename__ = "approval_request_approvers"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_requests.request_id", ondelete="CASCADE"), nullable=False, index=True)
    approver_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    approver_role = Column(String(100), nullable=False)
    step_number = Column(Integer, nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending, approved, rejected
    approved_amount_minor = Column(Integer, nullable=True)
    notes = Column(String(500), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    escalation_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('ix_approval_request_approver_status', 'status'),
        Index('ix_approval_request_approver_step', 'request_id', 'step_number'),
    )


class ApprovalLog(Base):
    """Immutable approval action log"""
    __tablename__ = "approval_logs"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_requests.request_id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    action = Column(String(30), nullable=False)  # created, approved, partial_approved, rejected, expired, escalated
    amount_minor = Column(Integer, nullable=True)
    remaining_amount_minor = Column(Integer, nullable=True)
    comment = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ApproverLimit(Base):
    """Approver limits with reset windows"""
    __tablename__ = "approver_limits"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approver_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_id = Column(SQLUUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="SET NULL"), nullable=True, index=True)
    limit_amount_minor = Column(Integer, nullable=False)
    consumed_amount_minor = Column(Integer, nullable=False, default=0)
    reset_period = Column(String(20), default="daily", nullable=False)  # daily, weekly, monthly, custom
    reset_anchor = Column(DateTime(timezone=True), nullable=True)
    last_reset_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

#New Code - Sebin
class PaymentTransaction(Base):
    """Payment transactions table"""
    __tablename__ = "payment_transactions"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    vendor_id = Column(SQLUUID(as_uuid=True), ForeignKey('vendors.vendor_id'), nullable=True)
    provider = Column(String(50), nullable=False)
    payment_intent_id = Column(String(255), nullable=True)
    charge_id = Column(String(255), nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default='GBP')  # ForeignKey('currencies.code') removed - table not needed
    status = Column(String(50), nullable=False)
    order_id = Column(SQLUUID(as_uuid=True), nullable=True)
    site_id = Column(SQLUUID(as_uuid=True), nullable=True)
    store_id = Column(SQLUUID(as_uuid=True), nullable=True)
    user_id = Column(SQLUUID(as_uuid=True), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    raw_response = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))


class Customer(Base):
    """Customers table"""
    __tablename__ = "customers"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False)
    external_customer_id = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))


class PaymentRefund(Base):
    """Payment refunds table"""
    __tablename__ = "payment_refunds"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(SQLUUID(as_uuid=True), ForeignKey('payment_transactions.id'), nullable=False)
    refund_id = Column(String(255), nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default='GBP')
    reason = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False)
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))


class PaymentAdjustment(Base):
    """Payment adjustments table"""
    __tablename__ = "payment_adjustments"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(SQLUUID(as_uuid=True), ForeignKey('payment_transactions.id'), nullable=False)
    adjustment_type = Column(String(50), nullable=False)
    adjustment_amount_minor = Column(BigInteger, nullable=False)
    adjustment_reason = Column(Text, nullable=True)
    currency = Column(String(3), nullable=False, default='GBP')
    is_applied = Column(Boolean, nullable=False, default=False)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'))


class TradeAccount(Base):
    """Trade account for business customers"""
    __tablename__ = "trade_accounts"

    trade_account_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    account_number = Column(String(100), nullable=False, unique=True)
    company_name = Column(String(200), nullable=False)
    contact_email = Column(String(255), nullable=False)
    credit_limit_minor = Column(BigInteger, nullable=False, default=0)
    available_credit_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    payment_terms_days = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'))
    updated_at = Column(DateTime(timezone=True), server_default=text('NOW()'), onupdate=text('NOW()'))


class PaymentIntent(Base):
    """Payment intent for transaction processing"""
    __tablename__ = "payment_intents"

    payment_intent_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    order_id = Column(SQLUUID(as_uuid=True), nullable=True)
    trade_account_id = Column(SQLUUID(as_uuid=True), ForeignKey('trade_accounts.trade_account_id'), nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default='GBP')
    status = Column(String(20), nullable=False, default='pending')
    provider = Column(String(50), nullable=False)
    provider_intent_id = Column(String(255), nullable=True)
    payment_method = Column(String(50), nullable=True)
    payment_metadata = Column(JSONB, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    succeeded_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'))
    updated_at = Column(DateTime(timezone=True), server_default=text('NOW()'), onupdate=text('NOW()'))


class CurrencyRate(Base):
    """Currency exchange rates"""
    __tablename__ = "currency_rates"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_currency = Column(String(3), nullable=False)
    target_currency = Column(String(3), nullable=False)
    rate = Column(String(50), nullable=False)
    source = Column(String(50), nullable=False, default='manual')
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'))


class PaymentWebhook(Base):
    """Payment webhook events"""
    __tablename__ = "payment_webhooks"

    webhook_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    processed = Column(Boolean, nullable=False, default=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'))

class Order(Base):
    """Order entity"""
    __tablename__ = "orders"

    order_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aifi_order_id = Column(String(50), nullable=True, unique=True)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    site_id = Column(SQLUUID(as_uuid=True), nullable=True)
    store_id = Column(SQLUUID(as_uuid=True), nullable=True)
    customer_id = Column(SQLUUID(as_uuid=True), nullable=False)
    order_number = Column(String(50), nullable=False, unique=True)
    order_status = Column(String(20), nullable=False, default='pending')
    order_type = Column(String(20), nullable=False, default='purchase')
    total_amount_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    payment_status = Column(String(20), nullable=False, default='pending')
    fulfillment_status = Column(String(20), nullable=False, default='pending')
    approval_request_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_requests.request_id"), nullable=True, index=True)
    shipping_address = Column(JSON, nullable=True)
    billing_address = Column(JSON, nullable=True)
    order_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AifiStoreMap(Base):
    """Mapping between AiFi storeId (numeric/string) and our Store UUID."""
    __tablename__ = "aifi_store_mappings"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aifi_store_id = Column(String(64), nullable=False, unique=True, index=True)
    store_id = Column(SQLUUID(as_uuid=True), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class OrderItem(Base):
    """Order item entity"""
    __tablename__ = "order_items"

    item_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(SQLUUID(as_uuid=True), ForeignKey('orders.order_id'), nullable=False)
    product_id = Column(SQLUUID(as_uuid=True), nullable=False)
    variant_id = Column(SQLUUID(as_uuid=True), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    total_price_minor = Column(Integer, nullable=False)
    item_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class VendorSettlement(Base):
    """Vendor Settlement: Main settlement record for vendor payouts"""
    __tablename__ = "vendor_settlements"

    settlement_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(SQLUUID(as_uuid=True), nullable=False)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    settlement_period_start = Column(Date, nullable=False)
    settlement_period_end = Column(Date, nullable=False)
    total_sales_minor = Column(BigInteger, nullable=False, default=0)
    total_commission_minor = Column(BigInteger, nullable=False, default=0)
    total_adjustments_minor = Column(BigInteger, nullable=False, default=0)
    net_settlement_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    settlement_status = Column(String(20), nullable=False, default='pending')
    settlement_date = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship("VendorSettlementItem", back_populates="settlement")
    adjustments = relationship("VendorSettlementAdjustment", back_populates="settlement")
    # disputes relationship removed - VendorDispute links to settlement_item, not settlement


class VendorSettlementItem(Base):
    """Vendor Settlement Item: Individual items within a settlement"""
    __tablename__ = "vendor_settlement_items"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(SQLUUID(as_uuid=True), nullable=False)
    settlement_id = Column(SQLUUID(as_uuid=True), ForeignKey('vendor_settlements.settlement_id'), nullable=False)
    vendor_id = Column(SQLUUID(as_uuid=True), nullable=False)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    payout_amount_minor = Column(BigInteger, nullable=False)
    commission_amount_minor = Column(BigInteger, nullable=False)
    fee_amount_minor = Column(BigInteger, nullable=False, default=0)
    net_amount_minor = Column(BigInteger, nullable=False)
    settlement_status = Column(String(20), nullable=False, default='pending')
    paid_out_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    settlement = relationship("VendorSettlement", back_populates="items")
    adjustments = relationship("VendorSettlementAdjustment", back_populates="settlement_item")
    disputes = relationship("VendorDispute", back_populates="settlement_item")


class VendorSettlementAdjustment(Base):
    """Vendor Settlement Adjustment: Adjustments to settlement amounts"""
    __tablename__ = "vendor_settlement_adjustments"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_id = Column(SQLUUID(as_uuid=True), ForeignKey('vendor_settlements.settlement_id'), nullable=False)
    settlement_item_id = Column(SQLUUID(as_uuid=True), ForeignKey('vendor_settlement_items.id'), nullable=True)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    adjustment_amount_minor = Column(BigInteger, nullable=False)
    adjustment_reason = Column(String(255), nullable=False)
    adjustment_type = Column(String(20), nullable=False)
    currency = Column(String(3), nullable=False)
    adjustment_status = Column(String(20), nullable=False, default='pending')
    adjustment_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    settlement = relationship("VendorSettlement", back_populates="adjustments")
    settlement_item = relationship("VendorSettlementItem", back_populates="adjustments")


class VendorDispute(Base):
    """Vendor Dispute: Disputes related to settlements or items"""
    __tablename__ = "vendor_disputes"

    dispute_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_item_id = Column(SQLUUID(as_uuid=True), ForeignKey('vendor_settlement_items.id'), nullable=False)
    vendor_id = Column(SQLUUID(as_uuid=True), nullable=False)
    dispute_type = Column(String(50), nullable=False)
    dispute_reason = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='open')
    resolution = Column(String(20), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    sla_deadline = Column(DateTime(timezone=True), nullable=False)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)

    settlement_item = relationship("VendorSettlementItem", back_populates="disputes")


class VendorSettlementBatch(Base):
    """Vendor Settlement Batch: Batch processing for settlements"""
    __tablename__ = "vendor_settlement_batches"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    batch_number = Column(String(50), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default='processing')
    total_amount_minor = Column(BigInteger, nullable=False, default=0)
    settlement_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AifiSession(Base):
    """AiFi session tracking"""
    __tablename__ = "aifi_sessions"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=True, index=True)
    aifi_session_id = Column(String(64), nullable=False, unique=True, index=True)
    customer_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    store_id = Column(SQLUUID(as_uuid=True), ForeignKey("stores.store_id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), nullable=True)
    session_token = Column(String(128), nullable=True)
    code = Column(String(128), nullable=True)
    session_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Budget(Base):
    """Budget for cost centres - Phase 4"""
    __tablename__ = "budgets"

    budget_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey('cost_centres.cost_centre_id'), nullable=False)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    budget_year = Column(Integer, nullable=False)
    budget_month = Column(Integer, nullable=False)
    budget_type = Column(String(50), nullable=False)
    budget_amount_minor = Column(BigInteger, nullable=False)
    spent_amount_minor = Column(BigInteger, nullable=False, default=0)
    available_amount_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    status = Column(String(20), nullable=False, default='active')
    approval_workflow_id = Column(SQLUUID(as_uuid=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BudgetTransaction(Base):
    """Budget transactions for spend tracking - Phase 4"""
    __tablename__ = "budget_transactions"

    transaction_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id = Column(SQLUUID(as_uuid=True), ForeignKey('budgets.budget_id'), nullable=False)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    transaction_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    reference_id = Column(String(100), nullable=True)
    reference_type = Column(String(50), nullable=True)
    approval_id = Column(SQLUUID(as_uuid=True), nullable=True)
    is_approved = Column(Boolean, nullable=False, default=False)
    created_by = Column(SQLUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BudgetAlert(Base):
    """Budget alerts for overspend notifications - Phase 4"""
    __tablename__ = "budget_alerts"

    alert_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id = Column(SQLUUID(as_uuid=True), ForeignKey('budgets.budget_id'), nullable=False)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    alert_type = Column(String(50), nullable=False)
    threshold_percentage = Column(Numeric(5, 2), nullable=False)
    message = Column(Text, nullable=False)
    is_acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_by = Column(SQLUUID(as_uuid=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TradeInvoice(Base):
    """Trade Invoice: Tenant invoices for billing"""
    __tablename__ = "trade_invoices"

    id = Column(String(120), primary_key=True)
    tenant_id = Column(String(100), nullable=False)
    invoice_number = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default='draft')
    amount_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    tax_total_minor = Column(BigInteger, nullable=False, default=0)
    subtotal_minor = Column(BigInteger, nullable=False, default=0)
    due_date = Column(Date, nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    ar_customer_code = Column(String(100), nullable=True)
    terms = Column(String(20), nullable=False, default='NET30')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lines = relationship("TradeInvoiceLine", back_populates="invoice")


class TradeInvoiceLine(Base):
    """Trade Invoice Line: Line items for invoices"""
    __tablename__ = "trade_invoice_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(String(120), ForeignKey('trade_invoices.id'), nullable=False)
    line_number = Column(Integer, nullable=False)
    description = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price_minor = Column(BigInteger, nullable=False)
    line_total_minor = Column(BigInteger, nullable=False)
    tax_minor = Column(BigInteger, nullable=False, default=0)
    tax_code = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    invoice = relationship("TradeInvoice", back_populates="lines")


class BillingOutboxEvent(Base):
    """Billing Outbox Event: For reliable event publishing"""
    __tablename__ = "billing_outbox_events"

    event_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_id = Column(SQLUUID(as_uuid=True), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

class LedgerEntryNew(Base):
    """Enhanced ledger entry with v4.1 features"""
    __tablename__ = "ledger_entries_new"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    vendor_id = Column(SQLUUID(as_uuid=True), nullable=True)
    account = Column(String(100), nullable=False)
    entry_type = Column(String(20), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    cost_centre_id = Column(SQLUUID(as_uuid=True), nullable=True)
    site_id = Column(SQLUUID(as_uuid=True), nullable=True)
    store_id = Column(SQLUUID(as_uuid=True), nullable=True)
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    entry_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class AccountBalanceNew(Base):
    """Precomputed account balances for performance"""
    __tablename__ = "account_balances_new"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account = Column(String(100), nullable=False)
    currency = Column(String(3), nullable=False)
    balance_minor = Column(BigInteger, nullable=False, server_default='0')
    last_updated = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEvent(Base):
    """Outbox pattern for reliable event publishing"""
    __tablename__ = "outbox_events"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Audit trail for all operations"""
    __tablename__ = "audit_logs"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=True)
    user_id = Column(SQLUUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    session_id = Column(String(100), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    severity = Column(String(20), nullable=False, default="info")
    category = Column(String(50), nullable=False, default="system")
    retention_until = Column(DateTime(timezone=True), nullable=True)


class IdempotencyRecord(Base):
    """Idempotency records to prevent duplicate operations"""
    __tablename__ = "idempotency_records"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False)
    user_id = Column(SQLUUID(as_uuid=True), nullable=True)
    request_hash = Column(String(255), nullable=False)
    response_data = Column(JSONB, nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class SpendingEvent(Base):
    """Spending events for budget tracking and audit"""
    __tablename__ = "spending_events"
    
    event_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(50), nullable=False)  # budget_allocated, budget_spent, order_created
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id"), nullable=False, index=True)
    order_id = Column(SQLUUID(as_uuid=True), ForeignKey("orders.order_id"), nullable=True, index=True)
    approval_request_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_requests.request_id"), nullable=True, index=True)
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


class InstantBudgetRequest(Base):
    """Instant budget request model"""
    __tablename__ = "instant_budget_requests"
    
    request_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"), nullable=False, index=True)
    store_id = Column(SQLUUID(as_uuid=True), ForeignKey("stores.store_id", ondelete="SET NULL"), nullable=True, index=True)
    requested_amount_minor = Column(BigInteger, nullable=False)
    approved_amount_minor = Column(BigInteger, nullable=False, default=0)
    remaining_amount_minor = Column(BigInteger, nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending, approved, rejected, expired, partial
    requested_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    approved_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables initialized")
except Exception as e:
    logger.error(f"❌ Table initialization failed: {e}")

