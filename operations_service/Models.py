from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, func, UUID, BigInteger, text, Text, JSON, \
    Date, Numeric, Index, Enum
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base, relationship, backref
import uuid

from provisioning_service.core.db_config import engine
from provisioning_service.utils.logger import logger

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


class CostCentre(Base):
    """Cost Centre model - budget tracking"""
    __tablename__ = "cost_centres"

    cost_centre_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)

    code = Column(String(50), nullable=False)  # unique per tenant
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    owner_user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)

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
    clearance_request_id = Column(UUID(as_uuid=True), ForeignKey("approval_requests.request_id"), nullable=True)

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
    clearance_request = relationship("ApprovalRequest", foreign_keys=[clearance_request_id])


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
    chain_id = Column(SQLUUID(as_uuid=True), ForeignKey("approval_chains.chain_id"), nullable=True, index=True)
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
    cost_centre_id = Column(SQLUUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="SET NULL"), nullable=True, index=True)
    limit_amount_minor = Column(Integer, nullable=False)
    consumed_amount_minor = Column(Integer, nullable=False, default=0)
    reset_period = Column(String(20), default="daily", nullable=False)  # daily, weekly, monthly, custom
    reset_anchor = Column(DateTime(timezone=True), nullable=True)
    last_reset_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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

class BudgetRequest(Base):
    __tablename__ = "budget_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    amount = Column(Numeric(12, 2), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        Enum("pending", "partially_approved", "fully_approved", "rejected", name="budget_status"),
        default="pending",
        nullable=False
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    approvals = relationship("BudgetApproval", back_populates="budget_request")


class BudgetApproval(Base):
    __tablename__ = "budget_approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    budget_request_id = Column(Integer, ForeignKey("budget_requests.id"), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    approved_amount = Column(Numeric(12, 2), nullable=False)
    decision = Column(
        Enum("pending", "approved", "rejected", name="approval_decision"),
        default="pending",
        nullable=False
    )
    comments = Column(Text, nullable=True)
    decided_at = Column(DateTime, default=datetime.utcnow)

    budget_request = relationship("BudgetRequest", back_populates="approvals")
