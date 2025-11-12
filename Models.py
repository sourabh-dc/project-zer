from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, func, UUID, BigInteger, text, Text, JSON
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base
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
    name = Column(String(255), nullable=False, unique=True)
    tenant_type = Column("tenant_type", String(50), nullable=False)  # customer, retailer, distributor
    active = Column(Boolean, default=True, index=True)
    tenant_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Site(Base):
    """Site model - physical locations under a tenant"""
    __tablename__ = "sites"
    site_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    site_type = Column(String(50), nullable=False)
    geo = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
    """User model - tenant-level users"""
    __tablename__ = "users"
    user_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)
    active = Column(Boolean, default=True, index=True)
    api_key = Column(String(255), unique=True, index=True)
    api_key_created_at = Column(DateTime(timezone=True))
    api_key_expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
    role_id = Column(SQLUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id = Column(SQLUUID(as_uuid=True), ForeignKey("permissions.permission_id", ondelete="CASCADE"), nullable=False, index=True)
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
    budget_minor = Column(Integer, default=0)  # Amount in minor units (pence/cents)
    spent_minor = Column(Integer, default=0)
    currency_code = Column(String(3), default="GBP")
    status = Column(String(50), default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SubscriptionPlan(Base):
    """Subscription plan model - defines pricing tiers"""
    __tablename__ = "subscription_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    price_yearly_minor = Column(Integer, nullable=False)  # Price in minor units (pence/cents)
    currency = Column(String(3), default="GBP", nullable=False)
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Feature(Base):
    """Feature model - defines available system features"""
    __tablename__ = "features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    category = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanFeature(Base):
    """Plan-Feature mapping - links features to plans with limits"""
    __tablename__ = "plan_features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code", ondelete="CASCADE"), nullable=False, index=True)
    feature_code = Column(String(50), ForeignKey("features.code", ondelete="CASCADE"), nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    limits = Column(JSONB, nullable=True)  # e.g., {"rate_limit": 1000, "tier": "basic"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantSubscription(Base):
    """Tenant subscription model - tracks tenant plan subscriptions"""
    __tablename__ = "tenant_subscriptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code"), nullable=False)
    payment_method = Column(String(20), nullable=False)  # stripe, trade, etc.
    status = Column(String(50), nullable=False, index=True)  # active, canceled, etc.
    external_id = Column(String(100), index=True, nullable=True)  # External payment provider ID
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    trial_end = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
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
    """Product model - catalog items"""
    __tablename__ = "products"
    product_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(SQLUUID(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True, index=True)
    sku = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    brand = Column(String(100), nullable=True, index=True)
    manufacturer = Column(String(255), nullable=True)
    base_price_minor = Column(Integer, nullable=False)  # Base price in minor units
    currency = Column(String(3), default="GBP", nullable=False)
    tax_rate = Column(Integer, default=0)  # Tax rate in basis points (e.g., 2000 = 20%)
    product_type = Column(String(50), nullable=True, index=True)  # physical, digital, service
    active = Column(Boolean, default=True, nullable=False, index=True)
    product_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
    chain_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_chains.chain_id"), nullable=False, index=True)
    request_number = Column(String(50), nullable=False, unique=True, index=True)
    request_type = Column(String(50), nullable=False, index=True)  # budget, order, vendor
    request_data = Column(JSONB, nullable=False)
    requested_by = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    request_status = Column(String(20), default="pending", nullable=False, index=True)  # pending, approved, denied
    current_step_number = Column(Integer, default=1, nullable=False)
    total_amount_minor = Column(Integer, nullable=True)
    currency = Column(String(3), default="GBP", nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
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
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending, approved, denied
    notes = Column(String(500), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    escalation_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

#New Code - Sebin
class PaymentTransaction(Base):
    """Payment transactions table"""
    __tablename__ = "payment_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey('vendors.vendor_id'), nullable=True)
    provider = Column(String(50), nullable=False)
    payment_intent_id = Column(String(255), nullable=True)
    charge_id = Column(String(255), nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), ForeignKey('currencies.code'), nullable=False, default='GBP')
    status = Column(String(50), nullable=False)
    order_id = Column(UUID(as_uuid=True), nullable=True)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    raw_response = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))


class Customer(Base):
    """Customers table"""
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey('payment_transactions.id'), nullable=False)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey('payment_transactions.id'), nullable=False)
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

    trade_account_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
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

    payment_intent_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    order_id = Column(UUID(as_uuid=True), nullable=True)
    trade_account_id = Column(UUID(as_uuid=True), ForeignKey('trade_accounts.trade_account_id'), nullable=True)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    webhook_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    processed = Column(Boolean, nullable=False, default=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'))

class Order(Base):
    """Order entity"""
    __tablename__ = "orders"

    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    order_number = Column(String(50), nullable=False, unique=True)
    order_status = Column(String(20), nullable=False, default='pending')
    order_type = Column(String(20), nullable=False, default='purchase')
    total_amount_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    payment_status = Column(String(20), nullable=False, default='pending')
    fulfillment_status = Column(String(20), nullable=False, default='pending')
    shipping_address = Column(JSON, nullable=True)
    billing_address = Column(JSON, nullable=True)
    order_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OrderItem(Base):
    """Order item entity"""
    __tablename__ = "order_items"

    item_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey('orders.order_id'), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    total_price_minor = Column(Integer, nullable=False)
    item_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables initialized")
except Exception as e:
    logger.error(f"❌ Table initialization failed: {e}")