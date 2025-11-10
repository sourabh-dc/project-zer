"""
ZeroQue Provisioning Service - Simplified Production Version

A clean, powerful API for multi-tenant provisioning with PostgreSQL RLS.
"""

import os
import uuid
import json
import logging
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, EmailStr, field_validator
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Integer, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.exc import IntegrityError
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import redis
import bcrypt


class Settings(BaseSettings):
    """Application settings - simple and powerful"""
    DATABASE_URL: str = Field(
        default="postgresql://zeroque:zeroque@localhost:5432/zeroque_dev",
        description="PostgreSQL connection URL"
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching"
    )
    PORT: int = Field(default=8000, description="Service port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    
    # Production configuration
    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30
    API_KEY_EXPIRY_DAYS: int = 90
    CACHE_TTL_SECONDS: int = 300  # 5 minutes
    
    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()

SERVICE_NAME = "provisioning"
SERVICE_VERSION = "2.0.0"

# Configure logging
logging.basicConfig(
    level=getattr(logging, SETTINGS.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(SERVICE_NAME)

# Database setup
engine = create_engine(
    SETTINGS.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=SETTINGS.CONNECTION_POOL_SIZE,
    max_overflow=SETTINGS.MAX_OVERFLOW,
    pool_timeout=SETTINGS.POOL_TIMEOUT,
    pool_recycle=3600,
    isolation_level="READ COMMITTED"
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis setup
try:
    redis_client = redis.Redis.from_url(SETTINGS.REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("✅ Redis connected")
except Exception as e:
    redis_client = None
    logger.warning(f"⚠️  Redis unavailable: {e}, caching disabled")

# FastAPI app
app = FastAPI(
    title="ZeroQue Provisioning API",
    version=SERVICE_VERSION,
    description="Simple, powerful provisioning service with PostgreSQL RLS"
)

# CORS - configure via environment
allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Metrics
req_total = Counter('prov_requests_total', 'Total requests', ['operation', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Request duration', ['operation'])


# ==================================================================================
# DATABASE MODELS
# ==================================================================================

class Tenant(Base):
    """Tenant organization model"""
    __tablename__ = "tenants"
    tenant_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    type = Column(String(50), nullable=False)  # customer, retailer, distributor
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
    name = Column(String(255), nullable=False)
    code = Column(String(100), unique=True, nullable=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserRole(Base):
    """User-Role assignment model"""
    __tablename__ = "user_roles"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(SQLUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(SQLUUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
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


# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables initialized")
except Exception as e:
    logger.error(f"❌ Table initialization failed: {e}")


# ==================================================================================
# REQUEST/RESPONSE MODELS
# ==================================================================================

class TenantRequest(BaseModel):
    """Tenant creation request"""
    name: str = Field(min_length=1, max_length=255, description="Tenant name")
    type: str = Field(description="Tenant type: customer, retailer, or distributor")
    
    @field_validator('type')
    @classmethod
    def validate_tenant_type(cls, v):
        allowed = ["customer", "retailer", "distributor"]
        if v not in allowed:
            raise ValueError(f"Type must be one of: {', '.join(allowed)}")
        return v


class SiteRequest(BaseModel):
    """Site creation request"""
    name: str = Field(min_length=1, max_length=255, description="Site name")
    type: str = Field(description="Site type")
    geo: Optional[Dict] = Field(None, description="Geographic metadata (optional)")


class StoreRequest(BaseModel):
    """Store creation request"""
    name: str = Field(min_length=1, max_length=255, description="Store name")
    type: str = Field(description="Store type")
    geo: Optional[Dict] = Field(None, description="Geographic metadata (optional)")


class UserRequest(BaseModel):
    """User creation request"""
    email: EmailStr = Field(description="Valid email address")
    display_name: str = Field(min_length=1, max_length=255, description="Display name")
    tenant_id: str = Field(description="Tenant ID")
    password: str = Field(min_length=8, max_length=128, description="Password (min 8 chars)")
    
    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password strength"""
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v


class BulkUserRequest(BaseModel):
    """Bulk user import request"""
    tenant_id: str
    users: List[Dict[str, Any]]


class RoleRequest(BaseModel):
    """Role creation request"""
    name: str = Field(min_length=1, max_length=255, description="Role name (required)")
    code: Optional[str] = Field(None, max_length=100, description="Role code (optional)")
    description: Optional[str] = Field(None, max_length=500, description="Role description (optional)")


class VendorRequest(BaseModel):
    """Vendor creation request"""
    tenant_id: str
    name: str = Field(min_length=1, max_length=255, description="Vendor name")
    contact_email: Optional[EmailStr] = Field(None, description="Contact email (optional)")
    description: Optional[str] = Field(None, max_length=500, description="Description (optional)")


class CostCentreRequest(BaseModel):
    """Cost centre creation request"""
    tenant_id: str
    name: str = Field(min_length=1, max_length=200, description="Cost centre name")
    budget_minor: int = Field(ge=0, description="Budget in minor units (required)")
    manager_user_id: Optional[str] = Field(None, description="Manager user ID (optional)")


class SubscriptionPlanRequest(BaseModel):
    """Subscription plan creation request"""
    code: str = Field(min_length=1, max_length=50, description="Unique plan code")
    name: str = Field(min_length=1, max_length=100, description="Plan name")
    description: Optional[str] = Field(None, max_length=500, description="Plan description (optional)")
    price_yearly_minor: int = Field(ge=0, description="Yearly price in minor units")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")


class FeatureRequest(BaseModel):
    """Feature creation request"""
    code: str = Field(min_length=1, max_length=50, description="Unique feature code")
    name: str = Field(min_length=1, max_length=100, description="Feature name")
    description: Optional[str] = Field(None, max_length=500, description="Feature description (optional)")
    category: Optional[str] = Field(None, max_length=50, description="Feature category (optional)")


class PlanFeatureRequest(BaseModel):
    """Plan-feature association request"""
    limits: Optional[Dict[str, Any]] = Field(None, description="Feature limits (optional)")


class TenantSubscriptionRequest(BaseModel):
    """Tenant subscription creation request"""
    tenant_id: str = Field(description="Tenant ID")
    plan_code: str = Field(description="Plan code")
    payment_method: str = Field(default="stripe", description="Payment method")
    billing_cycle: str = Field(default="yearly", description="Billing cycle: yearly or monthly")
    auto_renew: bool = Field(default=True, description="Auto-renew subscription")


class CheckEntitlementRequest(BaseModel):
    """Check entitlement request"""
    tenant_id: str = Field(description="Tenant ID")
    feature_code: str = Field(description="Feature code to check")


class RecordUsageRequest(BaseModel):
    """Record usage request"""
    tenant_id: str = Field(description="Tenant ID")
    feature_code: str = Field(description="Feature code")
    usage_type: str = Field(description="Usage type identifier")
    count: int = Field(default=1, ge=1, description="Usage count")


class AssignRoleRequest(BaseModel):
    """Assign role to user request"""
    role_id: str = Field(description="Role ID to assign")


class CategoryRequest(BaseModel):
    """Category creation request"""
    tenant_id: str = Field(description="Tenant ID")
    name: str = Field(min_length=1, max_length=255, description="Category name")
    code: str = Field(min_length=1, max_length=100, description="Category code")
    description: Optional[str] = Field(None, max_length=500, description="Description (optional)")
    parent_category_id: Optional[str] = Field(None, description="Parent category ID (optional)")


class ProductRequest(BaseModel):
    """Product creation request"""
    tenant_id: str = Field(description="Tenant ID")
    category_id: Optional[str] = Field(None, description="Category ID (optional)")
    sku: str = Field(min_length=1, max_length=100, description="Product SKU")
    name: str = Field(min_length=1, max_length=255, description="Product name")
    description: Optional[str] = Field(None, max_length=1000, description="Product description")
    brand: Optional[str] = Field(None, max_length=100, description="Brand (optional)")
    manufacturer: Optional[str] = Field(None, max_length=255, description="Manufacturer (optional)")
    base_price_minor: int = Field(ge=0, description="Base price in minor units")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")
    tax_rate: int = Field(default=0, ge=0, description="Tax rate in basis points")
    product_type: Optional[str] = Field(None, description="Product type (optional)")
    product_metadata: Optional[Dict[str, Any]] = Field(None, description="Product metadata (optional)")


class VariantRequest(BaseModel):
    """Variant creation request"""
    product_id: str = Field(description="Product ID")
    sku: str = Field(min_length=1, max_length=100, description="Variant SKU (must be unique)")
    name: str = Field(min_length=1, max_length=255, description="Variant name")
    attributes: Optional[Dict[str, Any]] = Field(None, description="Variant attributes (optional)")
    price_minor: int = Field(ge=0, description="Price in minor units")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")
    stock_quantity: int = Field(default=0, ge=0, description="Stock quantity")
    low_stock_threshold: int = Field(default=10, ge=0, description="Low stock threshold")


class ApprovalChainRequest(BaseModel):
    """Approval chain creation request"""
    tenant_id: str = Field(description="Tenant ID")
    name: str = Field(min_length=1, max_length=255, description="Chain name")
    description: Optional[str] = Field(None, max_length=500, description="Chain description (optional)")
    chain_type: str = Field(description="Chain type (budget, purchase_order, vendor_onboarding)")
    is_active: bool = Field(default=True, description="Whether chain is active")


class ApprovalChainStepRequest(BaseModel):
    """Approval chain step creation request"""
    approval_chain_id: str = Field(description="Approval chain ID")
    step_number: int = Field(gt=0, description="Step number in the chain")
    approver_role: str = Field(description="Approver role (manager, finance_controller, director)")
    approver_scope: str = Field(description="Approver scope (site, tenant, store)")
    escalation_after_hours: Optional[int] = Field(None, gt=0, description="Hours before escalation (optional)")
    is_required: bool = Field(default=True, description="Whether this step is required")


class ApprovalRequestRequest(BaseModel):
    """Approval request creation request"""
    tenant_id: str = Field(description="Tenant ID")
    chain_id: str = Field(description="Approval chain ID to use")
    request_type: str = Field(description="Request type (budget, order, vendor)")
    request_data: Dict[str, Any] = Field(description="Request details")
    requested_by: str = Field(description="Requester user ID")
    total_amount_minor: Optional[int] = Field(None, ge=0, description="Amount in minor units (optional)")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")
    due_date: Optional[datetime] = Field(None, description="Due date (optional)")


class ApprovalResponseRequest(BaseModel):
    """Approval response request"""
    approver_user_id: str = Field(description="Approver user ID")
    approved: bool = Field(description="Whether to approve or deny")
    notes: Optional[str] = Field(None, max_length=500, description="Approval notes (optional)")


# ==================================================================================
# AUTHENTICATION & AUTHORIZATION
# ==================================================================================

def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"zq_{secrets.token_urlsafe(32)}"


def verify_api_key(api_key: str, db: Session) -> Optional[Dict]:
    """Verify API key and return user context"""
    try:
        user = db.query(User).filter(
            User.api_key == api_key,
            User.active == True
        ).first()
        
        if not user:
            return None
        
        # Check expiration
        if user.api_key_expires_at and datetime.now(timezone.utc) > user.api_key_expires_at:
            logger.warning(f"Expired API key used: {api_key[:10]}...")
            return None
        
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email
        }
    except Exception as e:
        logger.error(f"API key verification failed: {e}")
        return None


def get_user_context(x_api_key: Optional[str] = Header(None)):
    """Extract user context from API key"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    # Check cache first
    cache_key = f"apikey:{x_api_key[:20]}"
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache read failed: {e}")
    
    # Verify against database
    with SessionLocal() as db:
        ctx = verify_api_key(x_api_key, db)
        if not ctx:
            raise HTTPException(status_code=401, detail="Invalid or expired API key")
        
        # Cache for 5 minutes
        if redis_client:
            try:
                redis_client.setex(cache_key, SETTINGS.CACHE_TTL_SECONDS, json.dumps(ctx))
            except Exception as e:
                logger.warning(f"Cache write failed: {e}")
        
        return ctx


def set_rls_context(db: Session, tenant_id: str):
    """Set Row Level Security context for tenant isolation"""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
    except Exception as e:
        logger.error(f"RLS setup failed: {e}")
        raise HTTPException(status_code=500, detail="Security context setup failed")


def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Get database session with RLS enabled"""
    db = SessionLocal()
    try:
        set_rls_context(db, uctx["tenant_id"])
        yield db
    finally:
        db.close()


def get_db():
    """Get database session without RLS (for tenant creation)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant_from_cache(tenant_id: str, db: Session) -> Optional[Tenant]:
    """Get tenant with Redis caching"""
    cache_key = f"tenant:{tenant_id}"
    
    # Try cache first
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                tenant = Tenant()
                tenant.tenant_id = uuid.UUID(data["tenant_id"])
                tenant.name = data["name"]
                tenant.type = data["type"]
                tenant.active = data["active"]
                return tenant
        except Exception as e:
            logger.warning(f"Tenant cache read failed: {e}")
    
    # Query database
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
    if tenant and redis_client:
        try:
            data = {
                "tenant_id": str(tenant.tenant_id),
                "name": tenant.name,
                "type": tenant.type,
                "active": tenant.active
            }
            redis_client.setex(cache_key, SETTINGS.CACHE_TTL_SECONDS, json.dumps(data))
        except Exception as e:
            logger.warning(f"Tenant cache write failed: {e}")
    
    return tenant


# ==================================================================================
# API ENDPOINTS
# ==================================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "version": SERVICE_VERSION}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/tenants", status_code=201)
async def create_tenant(req: TenantRequest, db: Session = Depends(get_db)):
    """Create a new tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_tenant", status="start").inc()
        
        # Check if tenant exists
        existing = db.query(Tenant).filter(Tenant.name == req.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant name already exists")
        
        # Create tenant
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            name=req.name,
            type=req.type,
            active=True
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        
        req_total.labels(operation="create_tenant", status="success").inc()
        req_duration.labels(operation="create_tenant").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created tenant: {tenant.tenant_id} ({tenant.name})")
        
        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.type,
            "created_at": tenant.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_tenant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        raise HTTPException(status_code=409, detail="Tenant already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        logger.error(f"❌ Tenant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/tenants")
async def list_tenants(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List all tenants with pagination"""
    total = db.query(Tenant).filter(Tenant.active == True).count()
    tenants = (
        db.query(Tenant)
        .filter(Tenant.active == True)
        .order_by(Tenant.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    
    return {
        "tenants": [
            {
                "tenant_id": str(t.tenant_id),
                "name": t.name,
                "type": t.type,
                "created_at": t.created_at.isoformat()
            }
            for t in tenants
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/v1/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific tenant by ID"""
    try:
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.type,
            "active": tenant.active,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    name: Optional[str] = Query(None, description="New tenant name"),
    db: Session = Depends(get_db)
):
    """Update a tenant's information"""
    start = datetime.now()
    try:
        req_total.labels(operation="update_tenant", status="start").inc()
        
        # Find tenant
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Update fields
        if name:
            # Check if new name conflicts
            existing = db.query(Tenant).filter(
                Tenant.name == name,
                Tenant.tenant_id != uuid.UUID(tenant_id)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="Tenant name already exists")
            tenant.name = name
        
        tenant.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(tenant)
        
        # Clear cache
        if redis_client:
            try:
                redis_client.delete(f"tenant:{tenant_id}")
            except Exception as e:
                logger.warning(f"Cache clear failed: {e}")
        
        req_total.labels(operation="update_tenant", status="success").inc()
        req_duration.labels(operation="update_tenant").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Updated tenant: {tenant.tenant_id}")
        
        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.type,
            "active": tenant.active,
            "updated_at": tenant.updated_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="update_tenant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="update_tenant", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="update_tenant", status="error").inc()
        logger.error(f"❌ Update tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/sites", status_code=201)
async def create_site(
    req: SiteRequest,
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db)
):
    """Create a new site under a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_site", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create site
        site = Site(
            site_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            name=req.name,
            site_type=req.type,
            geo=req.geo
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        
        req_total.labels(operation="create_site", status="success").inc()
        req_duration.labels(operation="create_site").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created site: {site.site_id} ({site.name})")
        
        return {
            "site_id": str(site.site_id),
            "tenant_id": str(site.tenant_id),
            "name": site.name,
            "site_type": site.site_type,
            "created_at": site.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_site", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"❌ Site creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/sites")
async def list_sites(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List sites with optional tenant filtering"""
    try:
        q = db.query(Site)
        if tenant_id:
            q = q.filter(Site.tenant_id == uuid.UUID(tenant_id))
        
        total = q.count()
        sites = q.order_by(Site.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "sites": [
                {
                    "site_id": str(s.site_id),
                    "tenant_id": str(s.tenant_id),
                    "name": s.name,
                    "site_type": s.site_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in sites
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List sites failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/stores", status_code=201)
async def create_store(
    req: StoreRequest,
    site_id: str = Query(..., description="Site ID"),
    db: Session = Depends(get_db)
):
    """Create a new store under a site"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()
        
        # Verify site exists and get tenant_id
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        
        # Create store (tenant_id auto-mapped from site)
        store = Store(
            store_id=uuid.uuid4(),
            site_id=uuid.UUID(site_id),
            tenant_id=site.tenant_id,
            name=req.name,
            store_type=req.type,
            geo=req.geo
        )
        db.add(store)
        db.commit()
        db.refresh(store)
        
        req_total.labels(operation="create_store", status="success").inc()
        req_duration.labels(operation="create_store").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created store: {store.store_id} ({store.name})")
        
        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id),
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "created_at": store.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        req_total.labels(operation="create_store", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid site reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_store", status="error").inc()
        logger.error(f"❌ Store creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/stores")
async def list_stores(
    site_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List stores with optional site filtering"""
    try:
        q = db.query(Store)
        if site_id:
            q = q.filter(Store.site_id == uuid.UUID(site_id))
        
        total = q.count()
        stores = q.order_by(Store.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "stores": [
                {
                    "store_id": str(s.store_id),
                    "site_id": str(s.site_id),
                    "name": s.name,
                    "store_type": s.store_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in stores
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except Exception as e:
        logger.error(f"❌ List stores failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/users", status_code=201)
async def create_user(
    req: UserRequest,
    db: Session = Depends(get_db)
):
    """Create a new user"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_user", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Check if email exists
        existing = db.query(User).filter(func.lower(User.email) == req.email.lower()).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")
        
        # Hash password
        password_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Generate API key
        api_key = generate_api_key()
        api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)
        
        # Create user
        user = User(
            user_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            email=req.email.lower(),
            display_name=req.display_name,
            password_hash=password_hash,
            active=True,
            api_key=api_key,
            api_key_created_at=datetime.now(timezone.utc),
            api_key_expires_at=api_key_expires_at
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        req_total.labels(operation="create_user", status="success").inc()
        req_duration.labels(operation="create_user").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created user: {user.user_id} ({user.email})")
        
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "display_name": user.display_name,
            "api_key": api_key,
            "api_key_expires_at": api_key_expires_at.isoformat(),
            "created_at": user.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_user", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=409, detail="Email already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        logger.error(f"❌ User creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users")
async def list_users(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List users with optional tenant filtering"""
    try:
        q = db.query(User).filter(User.active == True)
        if tenant_id:
            q = q.filter(User.tenant_id == uuid.UUID(tenant_id))
        
        total = q.count()
        users = q.order_by(User.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "users": [
                {
                    "user_id": str(u.user_id),
                    "tenant_id": str(u.tenant_id),
                    "email": u.email,
                    "display_name": u.display_name,
                    "created_at": u.created_at.isoformat()
                }
                for u in users
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List users failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/users/bulk-import", status_code=201)
async def bulk_import_users(
    req: BulkUserRequest,
    db: Session = Depends(get_db)
):
    """Bulk import users"""
    start = datetime.now()
    try:
        req_total.labels(operation="bulk_import_users", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        results = {"success": [], "failed": []}
        tenant_uuid = uuid.UUID(req.tenant_id)
        
        for user_data in req.users:
            try:
                email = user_data.get("email")
                display_name = user_data.get("display_name", email)
                
                if not email:
                    results["failed"].append({"error": "Missing email", "data": user_data})
                    continue
                
                # Check if email exists
                if db.query(User).filter(func.lower(User.email) == email.lower()).first():
                    results["failed"].append({"email": email, "error": "Email already exists"})
                    continue
                
                # Generate random password
                temp_password = f"temp_{secrets.token_urlsafe(16)}"
                password_hash = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                # Generate API key
                api_key = generate_api_key()
                api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)
                
                # Create user
                user = User(
                    user_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    email=email.lower(),
                    display_name=display_name,
                    password_hash=password_hash,
                    active=True,
                    api_key=api_key,
                    api_key_created_at=datetime.now(timezone.utc),
                    api_key_expires_at=api_key_expires_at
                )
                db.add(user)
                db.flush()
                
                results["success"].append({
                    "user_id": str(user.user_id),
                    "email": email,
                    "api_key": api_key,
                    "temporary_password": temp_password
                })
            except Exception as e:
                results["failed"].append({"email": user_data.get("email", "unknown"), "error": str(e)})
        
        db.commit()
        
        req_total.labels(operation="bulk_import_users", status="success").inc()
        req_duration.labels(operation="bulk_import_users").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Bulk import: {len(results['success'])}/{len(req.users)} succeeded")
        
        return {
            "tenant_id": req.tenant_id,
            "total_requested": len(req.users),
            "success_count": len(results["success"]),
            "failed_count": len(results["failed"]),
            "results": results
        }
    except HTTPException:
        req_total.labels(operation="bulk_import_users", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="bulk_import_users", status="error").inc()
        logger.error(f"❌ Bulk import failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/roles", status_code=201)
async def create_role(
    req: RoleRequest,
    db: Session = Depends(get_db)
):
    """Create a new role"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_role", status="start").inc()
        
        # Check if code exists (if provided)
        if req.code:
            existing = db.query(Role).filter(Role.code == req.code).first()
            if existing:
                raise HTTPException(status_code=409, detail="Role code already exists")
        
        # Create role
        role = Role(
            role_id=uuid.uuid4(),
            name=req.name,
            code=req.code,
            description=req.description
        )
        db.add(role)
        db.commit()
        db.refresh(role)
        
        req_total.labels(operation="create_role", status="success").inc()
        req_duration.labels(operation="create_role").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created role: {role.role_id} ({role.name})")
        
        return {
            "role_id": str(role.role_id),
            "name": role.name,
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        raise HTTPException(status_code=409, detail="Role code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        logger.error(f"❌ Role creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/roles")
async def list_roles(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List all roles"""
    total = db.query(Role).count()
    roles = db.query(Role).order_by(Role.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "roles": [
            {
                "role_id": str(r.role_id),
                "name": r.name,
                "code": r.code,
                "description": r.description,
                "created_at": r.created_at.isoformat()
            }
            for r in roles
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/users/{user_id}/roles", status_code=201)
async def assign_role_to_user(
    user_id: str,
    req: AssignRoleRequest,
    db: Session = Depends(get_db)
):
    """Assign a role to a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="assign_role", status="start").inc()
        
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify role exists
        role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        # Check if assignment already exists
        existing = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(req.role_id)
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="Role already assigned to user")
        
        # Create assignment
        user_role = UserRole(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            role_id=uuid.UUID(req.role_id)
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)
        
        req_total.labels(operation="assign_role", status="success").inc()
        req_duration.labels(operation="assign_role").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Assigned role {req.role_id} to user {user_id}")
        
        return {
            "user_id": user_id,
            "role_id": req.role_id,
            "role_name": role.name,
            "assigned": True,
            "created_at": user_role.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="assign_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="assign_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        raise HTTPException(status_code=409, detail="Role assignment already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        logger.error(f"❌ Assign role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users/{user_id}/roles")
async def get_user_roles(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get all roles assigned to a user"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user roles
        user_roles = (
            db.query(UserRole, Role)
            .join(Role, UserRole.role_id == Role.role_id)
            .filter(UserRole.user_id == uuid.UUID(user_id))
            .all()
        )
        
        return {
            "user_id": user_id,
            "email": user.email,
            "display_name": user.display_name,
            "roles": [
                {
                    "role_id": str(r.role_id),
                    "role_code": r.code,
                    "role_name": r.name,
                    "assigned_at": ur.created_at.isoformat()
                }
                for ur, r in user_roles
            ],
            "total": len(user_roles)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user roles failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(
    user_id: str,
    role_id: str,
    db: Session = Depends(get_db)
):
    """Remove a role from a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_role", status="start").inc()
        
        # Find user role assignment
        user_role = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id)
        ).first()
        
        if not user_role:
            raise HTTPException(status_code=404, detail="Role assignment not found")
        
        db.delete(user_role)
        db.commit()
        
        req_total.labels(operation="remove_role", status="success").inc()
        req_duration.labels(operation="remove_role").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Removed role {role_id} from user {user_id}")
        
        return {
            "user_id": user_id,
            "role_id": role_id,
            "removed": True
        }
    except ValueError:
        req_total.labels(operation="remove_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="remove_role", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_role", status="error").inc()
        logger.error(f"❌ Remove role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/vendors", status_code=201)
async def create_vendor(
    req: VendorRequest,
    db: Session = Depends(get_db)
):
    """Create a new vendor"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_vendor", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create vendor
        vendor = Vendor(
            vendor_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            contact_email=req.contact_email,
            description=req.description,
            status="active"
        )
        db.add(vendor)
        db.commit()
        db.refresh(vendor)
        
        req_total.labels(operation="create_vendor", status="success").inc()
        req_duration.labels(operation="create_vendor").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created vendor: {vendor.vendor_id} ({vendor.name})")
        
        return {
            "vendor_id": str(vendor.vendor_id),
            "tenant_id": str(vendor.tenant_id),
            "name": vendor.name,
            "contact_email": vendor.contact_email,
            "status": vendor.status,
            "created_at": vendor.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_vendor", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_vendor", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_vendor", status="error").inc()
        logger.error(f"❌ Vendor creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/vendors")
async def list_vendors(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List vendors with optional tenant filtering"""
    q = db.query(Vendor)
    if tenant_id:
        q = q.filter(Vendor.tenant_id == uuid.UUID(tenant_id))
    
    total = q.count()
    vendors = q.order_by(Vendor.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "vendors": [
            {
                "vendor_id": str(v.vendor_id),
                "tenant_id": str(v.tenant_id),
                "name": v.name,
                "status": v.status,
                "created_at": v.created_at.isoformat()
            }
            for v in vendors
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/cost-centres", status_code=201)
async def create_cost_centre(
    req: CostCentreRequest,
    db: Session = Depends(get_db)
):
    """Create a new cost centre"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify manager user exists (if provided)
        manager_user_uuid = None
        if req.manager_user_id:
            manager = db.query(User).filter(User.user_id == uuid.UUID(req.manager_user_id)).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager user not found")
            manager_user_uuid = uuid.UUID(req.manager_user_id)
        
        # Create cost centre
        cc = CostCentre(
            cost_centre_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            manager_user_id=manager_user_uuid,
            budget_minor=req.budget_minor,
            spent_minor=0,
            currency_code="GBP",
            status="active"
        )
        db.add(cc)
        db.commit()
        db.refresh(cc)
        
        req_total.labels(operation="create_cost_centre", status="success").inc()
        req_duration.labels(operation="create_cost_centre").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created cost centre: {cc.cost_centre_id} ({cc.name})")
        
        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "name": cc.name,
            "budget_minor": cc.budget_minor,
            "spent_minor": cc.spent_minor,
            "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
            "status": cc.status,
            "created_at": cc.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        logger.error(f"❌ Cost centre creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/cost-centres")
async def list_cost_centres(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List cost centres with optional tenant filtering"""
    q = db.query(CostCentre).filter(CostCentre.status == "active")
    if tenant_id:
        q = q.filter(CostCentre.tenant_id == uuid.UUID(tenant_id))
    
    total = q.count()
    ccs = q.order_by(CostCentre.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "cost_centres": [
            {
                "cost_centre_id": str(cc.cost_centre_id),
                "tenant_id": str(cc.tenant_id),
                "name": cc.name,
                "budget_minor": cc.budget_minor,
                "spent_minor": cc.spent_minor,
                "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
                "status": cc.status,
                "created_at": cc.created_at.isoformat()
            }
            for cc in ccs
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


# ==================================================================================
# CATALOG MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/categories", status_code=201)
async def create_category(
    req: CategoryRequest,
    db: Session = Depends(get_db)
):
    """Create a new product category"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_category", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify parent category if provided
        parent_category_uuid = None
        if req.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == uuid.UUID(req.parent_category_id)).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent category not found")
            parent_category_uuid = uuid.UUID(req.parent_category_id)
        
        # Create category
        category = Category(
            category_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            code=req.code,
            description=req.description,
            parent_category_id=parent_category_uuid,
            active=True
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        
        req_total.labels(operation="create_category", status="success").inc()
        req_duration.labels(operation="create_category").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created category: {category.category_id} ({category.name})")
        
        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "created_at": category.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or parent category ID format")
    except HTTPException:
        req_total.labels(operation="create_category", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Category code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        logger.error(f"❌ Category creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories")
async def list_categories(
    tenant_id: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List categories"""
    try:
        q = db.query(Category)
        if tenant_id:
            q = q.filter(Category.tenant_id == uuid.UUID(tenant_id))
        if active is not None:
            q = q.filter(Category.active == active)
        
        total = q.count()
        categories = q.order_by(Category.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "categories": [
                {
                    "category_id": str(c.category_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "code": c.code,
                    "description": c.description,
                    "parent_category_id": str(c.parent_category_id) if c.parent_category_id else None,
                    "active": c.active,
                    "created_at": c.created_at.isoformat()
                }
                for c in categories
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List categories failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/catalog/products", status_code=201)
async def create_product(
    req: ProductRequest,
    db: Session = Depends(get_db)
):
    """Create a new product"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_product", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify category if provided
        category_uuid = None
        if req.category_id:
            category = db.query(Category).filter(Category.category_id == uuid.UUID(req.category_id)).first()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")
            category_uuid = uuid.UUID(req.category_id)
        
        # Create product
        product = Product(
            product_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            category_id=category_uuid,
            sku=req.sku,
            name=req.name,
            description=req.description,
            brand=req.brand,
            manufacturer=req.manufacturer,
            base_price_minor=req.base_price_minor,
            currency=req.currency,
            tax_rate=req.tax_rate,
            product_type=req.product_type,
            active=True,
            product_metadata=req.product_metadata
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        
        req_total.labels(operation="create_product", status="success").inc()
        req_duration.labels(operation="create_product").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created product: {product.product_id} ({product.name})")
        
        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "category_id": str(product.category_id) if product.category_id else None,
            "sku": product.sku,
            "name": product.name,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "created_at": product.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or category ID format")
    except HTTPException:
        req_total.labels(operation="create_product", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Product SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        logger.error(f"❌ Product creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products")
async def list_products(
    tenant_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List products"""
    try:
        q = db.query(Product)
        if tenant_id:
            q = q.filter(Product.tenant_id == uuid.UUID(tenant_id))
        if category_id:
            q = q.filter(Product.category_id == uuid.UUID(category_id))
        if active is not None:
            q = q.filter(Product.active == active)
        
        total = q.count()
        products = q.order_by(Product.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "products": [
                {
                    "product_id": str(p.product_id),
                    "tenant_id": str(p.tenant_id),
                    "category_id": str(p.category_id) if p.category_id else None,
                    "sku": p.sku,
                    "name": p.name,
                    "description": p.description,
                    "brand": p.brand,
                    "base_price_minor": p.base_price_minor,
                    "currency": p.currency,
                    "active": p.active,
                    "created_at": p.created_at.isoformat()
                }
                for p in products
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List products failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/catalog/variants", status_code=201)
async def create_variant(
    req: VariantRequest,
    db: Session = Depends(get_db)
):
    """Create a new product variant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_variant", status="start").inc()
        
        # Verify product exists and get tenant_id
        product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Create variant
        variant = Variant(
            variant_id=uuid.uuid4(),
            product_id=uuid.UUID(req.product_id),
            tenant_id=product.tenant_id,
            sku=req.sku,
            name=req.name,
            attributes=req.attributes,
            price_minor=req.price_minor,
            currency=req.currency,
            stock_quantity=req.stock_quantity,
            low_stock_threshold=req.low_stock_threshold,
            active=True
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)
        
        req_total.labels(operation="create_variant", status="success").inc()
        req_duration.labels(operation="create_variant").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created variant: {variant.variant_id} ({variant.name})")
        
        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "created_at": variant.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        req_total.labels(operation="create_variant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Variant SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        logger.error(f"❌ Variant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}")
async def get_product(
    product_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific product by ID"""
    try:
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get category details if exists
        category = None
        if product.category_id:
            category = db.query(Category).filter(Category.category_id == product.category_id).first()
        
        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "category_id": str(product.category_id) if product.category_id else None,
            "category_name": category.name if category else None,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "brand": product.brand,
            "manufacturer": product.manufacturer,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "tax_rate": product.tax_rate,
            "product_type": product.product_type,
            "active": product.active,
            "product_metadata": product.product_metadata,
            "created_at": product.created_at.isoformat(),
            "updated_at": product.updated_at.isoformat() if product.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/variants")
async def get_product_variants(
    product_id: str,
    db: Session = Depends(get_db)
):
    """Get all variants for a specific product"""
    try:
        # Verify product exists
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get variants
        variants = db.query(Variant).filter(
            Variant.product_id == uuid.UUID(product_id)
        ).order_by(Variant.created_at.desc()).all()
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "product_sku": product.sku,
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": len(variants)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/category")
async def get_product_category(
    product_id: str,
    db: Session = Depends(get_db)
):
    """Get category for a specific product"""
    try:
        # Get product
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get category
        if not product.category_id:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "category": None,
                "message": "No category assigned to this product"
            }
        
        category = db.query(Category).filter(Category.category_id == product.category_id).first()
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "category": {
                "category_id": str(category.category_id),
                "name": category.name,
                "code": category.code,
                "description": category.description,
                "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
                "active": category.active
            } if category else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants")
async def list_variants(
    product_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List product variants"""
    try:
        q = db.query(Variant)
        if product_id:
            q = q.filter(Variant.product_id == uuid.UUID(product_id))
        
        total = q.count()
        variants = q.order_by(Variant.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "product_id": str(v.product_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except Exception as e:
        logger.error(f"❌ List variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants/{variant_id}")
async def get_variant(
    variant_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific variant by ID"""
    try:
        variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(variant_id)).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")
        
        # Get product details
        product = db.query(Product).filter(Product.product_id == variant.product_id).first()
        
        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "product_name": product.name if product else None,
            "product_sku": product.sku if product else None,
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "low_stock_threshold": variant.low_stock_threshold,
            "active": variant.active,
            "created_at": variant.created_at.isoformat(),
            "updated_at": variant.updated_at.isoformat() if variant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid variant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get variant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories/{category_id}")
async def get_category(
    category_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific category by ID"""
    try:
        category = db.query(Category).filter(Category.category_id == uuid.UUID(category_id)).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Get parent category if exists
        parent = None
        if category.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == category.parent_category_id).first()
        
        # Get product count in this category
        product_count = db.query(Product).filter(Product.category_id == uuid.UUID(category_id)).count()
        
        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "description": category.description,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "parent_category_name": parent.name if parent else None,
            "active": category.active,
            "product_count": product_count,
            "created_at": category.created_at.isoformat(),
            "updated_at": category.updated_at.isoformat() if category.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/subscriptions/plans", status_code=201)
async def create_subscription_plan(
    req: SubscriptionPlanRequest,
    db: Session = Depends(get_db)
):
    """Create a new subscription plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_plan", status="start").inc()
        
        # Check if plan code exists
        existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Plan code already exists")
        
        # Create plan
        plan = SubscriptionPlan(
            code=req.code,
            name=req.name,
            description=req.description,
            price_yearly_minor=req.price_yearly_minor,
            currency=req.currency,
            active=True
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        
        req_total.labels(operation="create_plan", status="success").inc()
        req_duration.labels(operation="create_plan").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created subscription plan: {plan.id} ({plan.code})")
        
        return {
            "plan_id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "price_yearly_minor": plan.price_yearly_minor,
            "currency": plan.currency,
            "created_at": plan.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_plan", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        raise HTTPException(status_code=409, detail="Plan code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        logger.error(f"❌ Plan creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans")
async def list_subscription_plans(
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List subscription plans"""
    q = db.query(SubscriptionPlan)
    if active is not None:
        q = q.filter(SubscriptionPlan.active == active)
    
    total = q.count()
    plans = q.order_by(SubscriptionPlan.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "plans": [
            {
                "plan_id": p.id,
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "price_yearly_minor": p.price_yearly_minor,
                "currency": p.currency,
                "active": p.active,
                "created_at": p.created_at.isoformat()
            }
            for p in plans
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/subscriptions/features", status_code=201)
async def create_feature(
    req: FeatureRequest,
    db: Session = Depends(get_db)
):
    """Create a new feature"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_feature", status="start").inc()
        
        # Check if feature code exists
        existing = db.query(Feature).filter(Feature.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Feature code already exists")
        
        # Create feature
        feature = Feature(
            id=uuid.uuid4(),
            code=req.code,
            name=req.name,
            description=req.description,
            category=req.category,
            active=True
        )
        db.add(feature)
        db.commit()
        db.refresh(feature)
        
        req_total.labels(operation="create_feature", status="success").inc()
        req_duration.labels(operation="create_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created feature: {feature.id} ({feature.code})")
        
        return {
            "feature_id": str(feature.id),
            "code": feature.code,
            "name": feature.name,
            "category": feature.category,
            "created_at": feature.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_feature", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        raise HTTPException(status_code=409, detail="Feature code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        logger.error(f"❌ Feature creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/features")
async def list_features(
    active: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List features"""
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if category:
        q = q.filter(Feature.category == category)
    
    total = q.count()
    features = q.order_by(Feature.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "features": [
            {
                "feature_id": str(f.id),
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "active": f.active,
                "created_at": f.created_at.isoformat()
            }
            for f in features
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.put("/v1/subscriptions/plans/{plan_code}/features/{feature_code}", status_code=201)
async def add_feature_to_plan(
    plan_code: str,
    feature_code: str,
    req: PlanFeatureRequest,
    db: Session = Depends(get_db)
):
    """Add a feature to a plan with optional limits"""
    start = datetime.now()
    try:
        req_total.labels(operation="add_plan_feature", status="start").inc()
        
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Check if association exists
        existing = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()
        
        if existing:
            # Update existing
            existing.enabled = True
            existing.limits = req.limits or {}
            db.commit()
            action = "updated"
        else:
            # Create new
            plan_feature = PlanFeature(
                id=uuid.uuid4(),
                plan_code=plan_code,
                feature_code=feature_code,
                enabled=True,
                limits=req.limits or {}
            )
            db.add(plan_feature)
            db.commit()
            action = "added"
        
        req_total.labels(operation="add_plan_feature", status="success").inc()
        req_duration.labels(operation="add_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ {action.capitalize()} feature {feature_code} to plan {plan_code}")
        
        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "enabled": True,
            "limits": req.limits or {},
            "action": action
        }
    except HTTPException:
        req_total.labels(operation="add_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="add_plan_feature", status="error").inc()
        logger.error(f"❌ Add feature to plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans/{plan_code}/features")
async def get_plan_features(
    plan_code: str,
    db: Session = Depends(get_db)
):
    """Get all features for a plan"""
    try:
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get plan features with feature details
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == plan_code, PlanFeature.enabled == True)
            .all()
        )
        
        return {
            "plan_code": plan_code,
            "plan_name": plan.name,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "category": f.category,
                    "enabled": pf.enabled,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "total": len(features)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get plan features failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/subscriptions/plans/{plan_code}/features/{feature_code}")
async def remove_feature_from_plan(
    plan_code: str,
    feature_code: str,
    db: Session = Depends(get_db)
):
    """Remove a feature from a plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_plan_feature", status="start").inc()
        
        # Find plan feature association
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()
        
        if not plan_feature:
            raise HTTPException(status_code=404, detail="Feature not associated with plan")
        
        # Disable the feature
        plan_feature.enabled = False
        db.commit()
        
        req_total.labels(operation="remove_plan_feature", status="success").inc()
        req_duration.labels(operation="remove_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Removed feature {feature_code} from plan {plan_code}")
        
        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "removed": True
        }
    except HTTPException:
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        logger.error(f"❌ Remove feature from plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions", status_code=201)
async def create_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Create a subscription for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_subscription", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Check if subscription already exists
        existing = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Subscription already exists for tenant")
        
        # Calculate subscription periods
        now = datetime.now(timezone.utc)
        period_days = 365 if req.billing_cycle == "yearly" else 30
        
        # Create subscription
        subscription = TenantSubscription(
            tenant_id=uuid.UUID(req.tenant_id),
            plan_code=req.plan_code,
            payment_method=req.payment_method,
            status="active",
            external_id=f"sub_{req.tenant_id}_{int(now.timestamp())}",
            current_period_start=now,
            current_period_end=now + timedelta(days=period_days)
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        req_total.labels(operation="create_subscription", status="success").inc()
        req_duration.labels(operation="create_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created subscription: {subscription.id} for tenant {req.tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_subscription", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        raise HTTPException(status_code=409, detail="Subscription already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        logger.error(f"❌ Subscription creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/subscriptions/{tenant_id}")
async def get_subscription(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Get subscription details for a tenant"""
    try:
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Get plan details
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.code == subscription.plan_code
        ).first()
        
        # Get plan features
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == subscription.plan_code, PlanFeature.enabled == True)
            .all()
        )
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "plan_name": plan.name if plan else None,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/renew")
async def renew_subscription(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Renew a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="renew_subscription", status="start").inc()
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Extend subscription by 1 year
        if subscription.current_period_end:
            subscription.current_period_end = subscription.current_period_end + timedelta(days=365)
        else:
            subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=365)
        
        subscription.status = "active"
        subscription.canceled_at = None
        subscription.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        req_total.labels(operation="renew_subscription", status="success").inc()
        req_duration.labels(operation="renew_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Renewed subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "new_period_end": subscription.current_period_end.isoformat(),
            "renewed": True
        }
    except HTTPException:
        req_total.labels(operation="renew_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="renew_subscription", status="error").inc()
        logger.error(f"❌ Renew subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/cancel")
async def cancel_subscription(
    tenant_id: str,
    cancel_at_period_end: bool = Query(True),
    db: Session = Depends(get_db)
):
    """Cancel a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="cancel_subscription", status="start").inc()
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        now = datetime.now(timezone.utc)
        subscription.canceled_at = now
        
        if cancel_at_period_end:
            subscription.status = "canceling"  # Will be canceled at period end
        else:
            subscription.status = "canceled"
        
        subscription.updated_at = now
        db.commit()
        
        req_total.labels(operation="cancel_subscription", status="success").inc()
        req_duration.labels(operation="cancel_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Canceled subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "canceled_at": subscription.canceled_at.isoformat(),
            "canceled": True
        }
    except HTTPException:
        req_total.labels(operation="cancel_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="cancel_subscription", status="error").inc()
        logger.error(f"❌ Cancel subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# ENTITLEMENTS & USAGE TRACKING ENDPOINTS
# ==================================================================================

@app.post("/v1/entitlements/check")
async def check_entitlement(
    req: CheckEntitlementRequest,
    db: Session = Depends(get_db)
):
    """Check if tenant has access to a feature"""
    try:
        # Get tenant subscription
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id),
            TenantSubscription.status == "active"
        ).first()
        
        if not subscription:
            return {
                "allowed": False,
                "reason": "No active subscription found",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code
            }
        
        # Check if feature is in plan
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == subscription.plan_code,
            PlanFeature.feature_code == req.feature_code,
            PlanFeature.enabled == True
        ).first()
        
        if not plan_feature:
            return {
                "allowed": False,
                "reason": "Feature not available in subscription plan",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "plan_code": subscription.plan_code
            }
        
        # Check usage limits (if any)
        limits = plan_feature.limits or {}
        rate_limit = limits.get("rate_limit")
        
        if rate_limit:
            # Get current period usage
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            usage = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
                SubscriptionUsage.feature_code == req.feature_code,
                SubscriptionUsage.period_start >= month_start
            ).first()
            
            usage_count = usage.usage_count if usage else 0
            
            if usage_count >= rate_limit:
                return {
                    "allowed": False,
                    "reason": "Usage limit exceeded",
                    "tenant_id": req.tenant_id,
                    "feature_code": req.feature_code,
                    "usage": usage_count,
                    "limit": rate_limit,
                    "remaining": 0
                }
            
            return {
                "allowed": True,
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "usage": usage_count,
                "limit": rate_limit,
                "remaining": rate_limit - usage_count
            }
        
        # No limits, access allowed
        return {
            "allowed": True,
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "limits": limits
        }
    except Exception as e:
        logger.error(f"❌ Check entitlement failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/usage/record", status_code=201)
async def record_usage(
    req: RecordUsageRequest,
    db: Session = Depends(get_db)
):
    """Record feature usage for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="record_usage", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == req.feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Calculate current period
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate month end
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)
        
        # Find or create usage record
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
            SubscriptionUsage.feature_code == req.feature_code,
            SubscriptionUsage.usage_type == req.usage_type,
            SubscriptionUsage.period_start >= month_start,
            SubscriptionUsage.period_start < month_end
        ).first()
        
        if usage:
            # Update existing
            usage.usage_count += req.count
            usage.updated_at = now
        else:
            # Create new
            usage = SubscriptionUsage(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(req.tenant_id),
                feature_code=req.feature_code,
                usage_type=req.usage_type,
                usage_count=req.count,
                period_start=month_start,
                period_end=month_end
            )
            db.add(usage)
        
        db.commit()
        db.refresh(usage)
        
        req_total.labels(operation="record_usage", status="success").inc()
        req_duration.labels(operation="record_usage").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Recorded usage: {req.count} for feature {req.feature_code}, tenant {req.tenant_id}")
        
        return {
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "usage_type": req.usage_type,
            "count": req.count,
            "total_usage": usage.usage_count,
            "period_start": usage.period_start.isoformat(),
            "period_end": usage.period_end.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="record_usage", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="record_usage", status="error").inc()
        logger.error(f"❌ Record usage failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/entitlements/usage/{tenant_id}")
async def get_usage_summary(
    tenant_id: str,
    feature_code: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get usage summary for a tenant"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Build query
        q = db.query(SubscriptionUsage).filter(SubscriptionUsage.tenant_id == uuid.UUID(tenant_id))
        if feature_code:
            q = q.filter(SubscriptionUsage.feature_code == feature_code)
        
        # Get current period usage
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_usage = q.filter(SubscriptionUsage.period_start >= month_start).all()
        
        return {
            "tenant_id": tenant_id,
            "current_period": {
                "start": month_start.isoformat(),
                "usage": [
                    {
                        "feature_code": u.feature_code,
                        "usage_type": u.usage_type,
                        "count": u.usage_count,
                        "period_start": u.period_start.isoformat(),
                        "period_end": u.period_end.isoformat()
                    }
                    for u in current_usage
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get usage summary failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# APPROVALS MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/approvals/chains", status_code=201)
async def create_approval_chain(
    req: ApprovalChainRequest,
    db: Session = Depends(get_db)
):
    """Create a new approval chain"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_chain", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create approval chain
        chain = ApprovalChain(
            chain_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            description=req.description,
            chain_type=req.chain_type,
            is_active=req.is_active
        )
        db.add(chain)
        db.commit()
        db.refresh(chain)
        
        req_total.labels(operation="create_approval_chain", status="success").inc()
        req_duration.labels(operation="create_approval_chain").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval chain: {chain.chain_id} ({chain.name})")
        
        return {
            "chain_id": str(chain.chain_id),
            "tenant_id": str(chain.tenant_id),
            "name": chain.name,
            "description": chain.description,
            "chain_type": chain.chain_type,
            "is_active": chain.is_active,
            "created_at": chain.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_chain", status="error").inc()
        logger.error(f"❌ Approval chain creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/chains")
async def list_approval_chains(
    tenant_id: Optional[str] = Query(None),
    chain_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List approval chains"""
    try:
        q = db.query(ApprovalChain)
        if tenant_id:
            q = q.filter(ApprovalChain.tenant_id == uuid.UUID(tenant_id))
        if chain_type:
            q = q.filter(ApprovalChain.chain_type == chain_type)
        if is_active is not None:
            q = q.filter(ApprovalChain.is_active == is_active)
        
        total = q.count()
        chains = q.order_by(ApprovalChain.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "chains": [
                {
                    "chain_id": str(c.chain_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "description": c.description,
                    "chain_type": c.chain_type,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat()
                }
                for c in chains
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List approval chains failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/chains/steps", status_code=201)
async def create_approval_chain_step(
    req: ApprovalChainStepRequest,
    db: Session = Depends(get_db)
):
    """Create a new approval chain step"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_chain_step", status="start").inc()
        
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_id == uuid.UUID(req.approval_chain_id)
        ).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        # Create step
        step = ApprovalChainStep(
            id=uuid.uuid4(),
            approval_chain_id=uuid.UUID(req.approval_chain_id),
            step_number=req.step_number,
            approver_role=req.approver_role,
            approver_scope=req.approver_scope,
            escalation_after_hours=req.escalation_after_hours,
            is_required=req.is_required
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        
        req_total.labels(operation="create_chain_step", status="success").inc()
        req_duration.labels(operation="create_chain_step").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval chain step: {step.id}")
        
        return {
            "id": str(step.id),
            "approval_chain_id": str(step.approval_chain_id),
            "step_number": step.step_number,
            "approver_role": step.approver_role,
            "approver_scope": step.approver_scope,
            "escalation_after_hours": step.escalation_after_hours,
            "is_required": step.is_required,
            "created_at": step.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid approval chain ID format")
    except HTTPException:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_chain_step", status="error").inc()
        logger.error(f"❌ Chain step creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/chains/{chain_id}/steps")
async def list_chain_steps(
    chain_id: str,
    db: Session = Depends(get_db)
):
    """List steps for an approval chain"""
    try:
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(chain_id)
        ).order_by(ApprovalChainStep.step_number).all()
        
        return {
            "chain_id": chain_id,
            "chain_name": chain.name,
            "steps": [
                {
                    "id": str(s.id),
                    "step_number": s.step_number,
                    "approver_role": s.approver_role,
                    "approver_scope": s.approver_scope,
                    "escalation_after_hours": s.escalation_after_hours,
                    "is_required": s.is_required,
                    "created_at": s.created_at.isoformat()
                }
                for s in steps
            ],
            "total": len(steps)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chain ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List chain steps failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests", status_code=201)
async def create_approval_request(
    req: ApprovalRequestRequest,
    db: Session = Depends(get_db)
):
    """Create a new approval request"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_request", status="start").inc()
        
        # Verify tenant, chain, and user exist
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(req.chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        user = db.query(User).filter(User.user_id == uuid.UUID(req.requested_by)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Requester user not found")
        
        # Generate request number
        request_number = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        
        # Create approval request
        approval_request = ApprovalRequest(
            request_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            chain_id=uuid.UUID(req.chain_id),
            request_number=request_number,
            request_type=req.request_type,
            request_data=req.request_data,
            requested_by=uuid.UUID(req.requested_by),
            request_status="pending",
            current_step_number=1,
            total_amount_minor=req.total_amount_minor,
            currency=req.currency,
            due_date=req.due_date
        )
        db.add(approval_request)
        db.flush()  # Get the request_id
        
        # Get chain steps and create approver assignments
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(req.chain_id)
        ).order_by(ApprovalChainStep.step_number).all()
        
        for step in steps:
            # Get users with the approver role (simplified - in production, query role assignments)
            # For now, just create a placeholder approver assignment
            approver = ApprovalRequestApprover(
                id=uuid.uuid4(),
                request_id=approval_request.request_id,
                approver_user_id=uuid.UUID(req.requested_by),  # Placeholder
                approver_role=step.approver_role,
                step_number=step.step_number,
                status="pending"
            )
            db.add(approver)
        
        db.commit()
        db.refresh(approval_request)
        
        req_total.labels(operation="create_approval_request", status="success").inc()
        req_duration.labels(operation="create_approval_request").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval request: {approval_request.request_id}")
        
        return {
            "request_id": str(approval_request.request_id),
            "request_number": approval_request.request_number,
            "tenant_id": str(approval_request.tenant_id),
            "chain_id": str(approval_request.chain_id),
            "request_type": approval_request.request_type,
            "requested_by": str(approval_request.requested_by),
            "request_status": approval_request.request_status,
            "total_amount_minor": approval_request.total_amount_minor,
            "currency": approval_request.currency,
            "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
            "created_at": approval_request.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_request", status="error").inc()
        logger.error(f"❌ Approval request creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests")
async def list_approval_requests(
    tenant_id: Optional[str] = Query(None),
    request_type: Optional[str] = Query(None),
    request_status: Optional[str] = Query(None),
    requested_by: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List approval requests"""
    try:
        q = db.query(ApprovalRequest)
        if tenant_id:
            q = q.filter(ApprovalRequest.tenant_id == uuid.UUID(tenant_id))
        if request_type:
            q = q.filter(ApprovalRequest.request_type == request_type)
        if request_status:
            q = q.filter(ApprovalRequest.request_status == request_status)
        if requested_by:
            q = q.filter(ApprovalRequest.requested_by == uuid.UUID(requested_by))
        
        total = q.count()
        requests = q.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "requests": [
                {
                    "request_id": str(r.request_id),
                    "request_number": r.request_number,
                    "tenant_id": str(r.tenant_id),
                    "chain_id": str(r.chain_id),
                    "request_type": r.request_type,
                    "requested_by": str(r.requested_by),
                    "request_status": r.request_status,
                    "current_step_number": r.current_step_number,
                    "total_amount_minor": r.total_amount_minor,
                    "currency": r.currency,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "created_at": r.created_at.isoformat()
                }
                for r in requests
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List approval requests failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests/{request_id}")
async def get_approval_request(
    request_id: str,
    db: Session = Depends(get_db)
):
    """Get approval request details"""
    try:
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # Get approvers
        approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()
        
        return {
            "request_id": str(request.request_id),
            "request_number": request.request_number,
            "tenant_id": str(request.tenant_id),
            "chain_id": str(request.chain_id),
            "request_type": request.request_type,
            "request_data": request.request_data,
            "requested_by": str(request.requested_by),
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "total_amount_minor": request.total_amount_minor,
            "currency": request.currency,
            "due_date": request.due_date.isoformat() if request.due_date else None,
            "completed_date": request.completed_date.isoformat() if request.completed_date else None,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None
                }
                for a in approvers
            ],
            "created_at": request.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get approval request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests/{request_id}/approvers")
async def get_request_approvers(
    request_id: str,
    db: Session = Depends(get_db)
):
    """Get all approvers for an approval request"""
    try:
        # Verify request exists
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # Get approvers with user details
        approvers = db.query(ApprovalRequestApprover, User).join(
            User, ApprovalRequestApprover.approver_user_id == User.user_id
        ).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()
        
        return {
            "request_id": request_id,
            "request_number": request.request_number,
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_email": u.email,
                    "approver_name": u.display_name,
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None,
                    "escalation_sent": a.escalation_sent,
                    "created_at": a.created_at.isoformat()
                }
                for a, u in approvers
            ],
            "total": len(approvers)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get request approvers failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests/{request_id}/respond")
async def respond_to_approval_request(
    request_id: str,
    req: ApprovalResponseRequest,
    db: Session = Depends(get_db)
):
    """Respond to an approval request (approve or deny)"""
    start = datetime.now()
    try:
        req_total.labels(operation="respond_approval", status="start").inc()
        
        # Get the approval request
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        if approval_request.request_status != "pending":
            raise HTTPException(status_code=400, detail=f"Request is not pending (status: {approval_request.request_status})")
        
        # Find the approver assignment
        approver = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id),
            ApprovalRequestApprover.step_number == approval_request.current_step_number,
            ApprovalRequestApprover.status == "pending"
        ).first()
        
        if not approver:
            raise HTTPException(status_code=404, detail="Approver assignment not found or already responded")
        
        # Update approver response
        approver.status = "approved" if req.approved else "denied"
        approver.notes = req.notes
        approver.responded_at = datetime.now(timezone.utc)
        
        # Update request status
        if not req.approved:
            # Denial at any step fails the request
            approval_request.request_status = "denied"
            approval_request.completed_date = datetime.now(timezone.utc)
        else:
            # Check if there are more steps
            max_step = db.query(func.max(ApprovalChainStep.step_number)).filter(
                ApprovalChainStep.approval_chain_id == approval_request.chain_id
            ).scalar()
            
            if approval_request.current_step_number >= max_step:
                # Last step completed and approved
                approval_request.request_status = "approved"
                approval_request.completed_date = datetime.now(timezone.utc)
            else:
                # Move to next step
                approval_request.current_step_number += 1
        
        approval_request.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        req_total.labels(operation="respond_approval", status="success").inc()
        req_duration.labels(operation="respond_approval").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Approval request {request_id} {'approved' if req.approved else 'denied'} by {req.approver_user_id}")
        
        return {
            "request_id": request_id,
            "approver_user_id": req.approver_user_id,
            "status": approver.status,
            "notes": approver.notes,
            "responded_at": approver.responded_at.isoformat(),
            "request_status": approval_request.request_status,
            "current_step": approval_request.current_step_number,
            "completed": approval_request.request_status in ["approved", "denied"]
        }
    except ValueError:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="respond_approval", status="error").inc()
        logger.error(f"❌ Respond to approval failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"🚀 Starting {SERVICE_NAME} v{SERVICE_VERSION}")
    logger.info(f"📊 Database: {SETTINGS.DATABASE_URL.split('@')[1] if '@' in SETTINGS.DATABASE_URL else 'configured'}")
    logger.info(f"💾 Redis: {'enabled' if redis_client else 'disabled'}")
    logger.info(f"🔒 RLS: enabled for tenant isolation")
    
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS.PORT)

