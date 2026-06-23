import uuid
from datetime import datetime, date
from pydantic import field_validator, BaseModel, Field, EmailStr, ConfigDict, constr
from typing import Optional, Dict, List, Any
import re

# ==================================================================================
# REQUEST/RESPONSE MODELS
# ==================================================================================

class TenantRequest(BaseModel):
    """Tenant creation request"""
    tenant_name: Optional[str] = Field(None, max_length=200, description="tenant name")
    type: str = Field(description="Tenant type: customer, retailer, or distributor")
    registration_number: Optional[str] = Field(None, max_length=100, description="Registration number (optional)")
    email: EmailStr = Field(..., description="Tenant primary contact email")
    billing_email: Optional[EmailStr] = Field(None, description="Billing contact email")
    admin_email: EmailStr = Field(..., description="Admin contact email")
    admin_firstname: str = Field(min_length=1, max_length=150, description="Admin first name")
    admin_lastname: str = Field(min_length=1, max_length=150, description="Admin last name")
    password: str = Field(min_length=8, max_length=128, description="Admin password (min 8 chars)")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
    active: Optional[bool] = Field(True, description="Is tenant active?")
    default_currency: Optional[str] = Field("GBP", max_length=3, description="Default currency code")
    timezone: Optional[str] = Field("UTC", description="Timezone")
    locale: Optional[str] = Field("en_GB", description="Locale")
    billing_address: Optional[str] = Field(None, description="Billing address")
    primary_domain: Optional[str] = Field(None, description="Primary domain")
    logo: Optional[bytes] = Field(None, description="Logo binary data (raw bytes). Max size 2MB")
    industry: Optional[str] = Field(None, description="Industry")
    tech_contact_email: Optional[EmailStr] = Field(None, description="Technical contact email")
    support_contact_email: Optional[EmailStr] = Field(None, description="Support contact email")

    @field_validator('type')
    @classmethod
    def validate_tenant_type(cls, v):
        allowed = ["customer", "retailer", "distributor"]
        if v not in allowed:
            raise ValueError(f"Type must be one of: {', '.join(allowed)}")
        return v

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        if not re.match(r'^\+?\d{7,15}$', v):
            raise ValueError('Phone must be digits, optionally starting with + and 7-15 characters long')
        return v


class TenantUpdateRequest(BaseModel):
    tenant_id: str = Field(description="Tenant ID")
    name: str = Field(min_length=1, max_length=200, description="Company name")
    type: str = Field(description="Tenant type: customer, retailer, or distributor")
    registration_number: Optional[str] = Field(None, max_length=100, description="Registration number (optional)")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
    active: Optional[str] = Field("true", description="Is tenant active?")

    @field_validator('type')
    @classmethod
    def validate_tenant_type(cls, v):
        allowed = ["customer", "retailer", "distributor"]
        if v not in allowed:
            raise ValueError(f"Type must be one of: {', '.join(allowed)}")
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        if not re.match(r'^\+?\d{7,15}$', v):
            raise ValueError('Phone must be digits, optionally starting with + and 7-15 characters long')
        return v


class SiteRequest(BaseModel):
    tenant_id: str = Field(description="Tenant ID")
    name: str = Field(min_length=1, max_length=255, description="Site name")
    type: str = Field(description="Site type")
    geo: Optional[Dict] = Field(None, description="Geographic metadata (optional)")
    active: bool = Field(True, description="Is site active?")
    currency: Optional[constr(min_length=3, max_length=3)] = Field(None, description="Currency code (ISO 3-letter)")
    timezone: Optional[str] = Field(None, description="Timezone")
    language: Optional[str] = Field(None, description="Language / locale")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
    fax: Optional[str] = Field(None, description="Fax number (optional)")
    email: Optional[EmailStr] = Field(None, description="Contact email (optional)")
    url: Optional[str] = Field(None, description="Site URL (optional)")
    logo_url: Optional[str] = Field(None, description="Logo URL (optional)")
    primary_billing_address: Optional[Dict[str, Any]] = Field(None, description="Primary billing address (structured JSON)")
    primary_shipping_address: Optional[Dict[str, Any]] = Field(None, description="Primary shipping address (structured JSON)")
    shipping_addresses: Optional[List[Dict[str, Any]]] = Field(None, description="Additional shipping addresses (array of structured JSON)")
    external_id: Optional[str] = Field(None, description="External reference ID (optional)")
    is_headquarter: Optional[bool] = Field(False, description="Is this site the headquarter?")

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        if not re.match(r'^\+?\d{7,15}$', v):
            raise ValueError('Phone must be digits, optionally starting with + and 7-15 characters long')
        return v


class StoreRequest(BaseModel):
    """Store creation request"""
    tenant_id: str = Field(..., description="Tenant ID (UUID)")
    name: str = Field(..., min_length=1, max_length=255, description="Store name")
    store_type: str = Field(..., description="Store type")
    active: bool = Field(..., description="Is store active?")
    site_id: Optional[str] = Field(None, description="Site ID (UUID)")
    currency: Optional[constr(min_length=3, max_length=3)] = Field(None, description="Currency code (ISO 3-letter)")
    timezone: Optional[str] = Field(None, description="Timezone")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
    email: Optional[EmailStr] = Field(None, description="Contact email (optional)")
    url: Optional[str] = Field(None, description="Store URL (optional)")
    logo_url: Optional[str] = Field(None, description="Logo URL (optional)")
    primary_shipping_address: Optional[Dict[str, Any]] = Field(None, description="Primary shipping address (structured JSON)")
    pickup_address: Optional[Dict[str, Any]] = Field(None, description="Pickup address (structured JSON)")
    geo: Optional[Dict[str, Any]] = Field(None, description="Geographic metadata (jsonb)")
    external_id: Optional[str] = Field(None, description="External reference ID (optional)")
    fulfillment_mode: Optional[str] = Field(None, description="Fulfillment mode (optional)")
    inventory_policy: Optional[str] = Field(None, description="Inventory policy (optional)")

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        if not re.match(r'^\+?\d{7,15}$', v):
            raise ValueError('Phone must be digits, optionally starting with + and 7-15 characters long')
        return v


class UserRequest(BaseModel):
    """User creation request — identity fields only (no password)."""
    tenant_id: str = Field(..., description="Tenant ID (UUID)")
    email: EmailStr = Field(..., description="Valid email address")
    first_name: str = Field(..., min_length=1, max_length=255, description="First name")
    last_name: str = Field(..., min_length=1, max_length=255, description="Last name")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
    position: Optional[str] = Field(None, description="Position / job title (optional)")
    profile_image: Optional[str] = Field(None, description="Profile image URL (optional)")
    home_site_id: Optional[str] = Field(None, description="Home site ID (UUID, optional)")
    home_store_id: Optional[str] = Field(None, description="Home store ID (UUID, optional)")
    home_org_unit_id: Optional[str] = Field(None, description="Home org unit ID (UUID, optional)")
    all_locations: Optional[bool] = Field(False, description="Access to all locations (optional)")

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        if not re.match(r'^\+?\d{7,15}$', v):
            raise ValueError('Phone must be digits, optionally starting with + and 7-15 characters long')
        return v


class BulkUserRequest(BaseModel):
    """Bulk user import request"""
    tenant_id: str
    users: List[Dict[str, Any]]


class RoleRequest(BaseModel):
    """Role creation request"""
    code: str = Field(min_length=1, max_length=100, description="Role code (required)")
    description: Optional[str] = Field(None, max_length=500, description="Role description (optional)")


class TenantRoleRequest(BaseModel):
    """Tenant-scoped role creation"""
    code: str = Field(min_length=1, max_length=100, description="Role code (required)")
    description: Optional[str] = Field(None, max_length=500, description="Role description (optional)")


class TenantRolePermissionRequest(BaseModel):
    """Assign permission to tenant role"""
    permission_code: str = Field(min_length=1, max_length=150, description="Existing permission code")


class TenantRoleAssignRequest(BaseModel):
    """Assign tenant role to user"""
    role_id: str = Field(description="Tenant role ID")


class VendorRequest(BaseModel):
    tenant_id: str = Field(description="Tenant ID")
    """Vendor creation request"""
    name: str = Field(min_length=1, max_length=255, description="Vendor name")
    contact_email: Optional[EmailStr] = Field(None, description="Contact email (optional)")
    description: Optional[str] = Field(None, max_length=500, description="Description (optional)")


class CostCentreRequest(BaseModel):
    """Cost centre creation request"""
    tenant_id: str = Field(..., description="Tenant ID (UUID, FK->tenants.tenant_id)")
    code: str = Field(..., min_length=1, max_length=50, description="Cost centre code (varchar(50))")
    name: str = Field(..., min_length=1, max_length=255, description="Cost centre name (varchar(255))")
    description: Optional[str] = Field(None, max_length=500, description="Description (varchar(500), optional)")
    owner_user_id: Optional[str] = Field(None, description="Owner user ID (UUID, FK->users.user_id, optional)")
    is_active: Optional[bool] = Field(True, description="Is cost centre active?")

    fiscal_year: Optional[int] = Field(None, ge=2000, le=2100, description="Fiscal year (e.g. 2025)")
    period_type: Optional[str] = Field("annual", description="Period type: annual, quarterly, monthly, weekly")
    period_number: Optional[int] = Field(None, ge=1, description="Period number within the fiscal year (e.g. month or quarter number)")
    period_start: Optional[date] = Field(None, description="Period start date")
    period_end: Optional[date] = Field(None, description="Period end date")
    budget_amount_minor: Optional[int] = Field(None, ge=0, description="Budget amount in minor units for the period")

    created_by: str = Field(..., description="Created by user ID (UUID, FK->users.user_id)")


class OrgUnitRequest(BaseModel):
    """Organizational unit creation request"""
    tenant_id: str = Field(..., description="Tenant ID (UUID)")
    name: str = Field(min_length=1, max_length=255, description="Org unit name")
    type: str = Field(min_length=1, max_length=50, description="Type: directorate, business_unit, department, team, etc.")
    status: Optional[str] = Field("active", description="Status (e.g. active/inactive)")
    parent_org_unit_id: Optional[str] = Field(None, description="Parent org unit ID (UUID, optional)")
    code: Optional[str] = Field(None, max_length=100, description="Org unit code (optional)")
    description: Optional[str] = Field(None, max_length=1000, description="Description (optional)")
    manager_user_id: Optional[str] = Field(None, description="Manager user ID (UUID, optional)")
    external_id: Optional[str] = Field(None, description="External reference ID (optional)")
    path: Optional[str] = Field(None, description="Hierarchical path (e.g. /Company/Division/Team)")
    depth: Optional[int] = Field(None, ge=0, description="Depth in hierarchy (root = 0)")


class OrgUnitAssignmentRequest(BaseModel):
    """User to org unit assignment request"""
    user_id: str = Field(..., description="User ID (UUID)")
    org_unit_id: str = Field(..., description="Org unit ID (UUID)")
    role_id: str = Field(..., description="Role ID (UUID)")
    assigned_by: Optional[str] = Field(None, description="Assigned by user ID (UUID, optional)")


class SiteUpdateRequest(BaseModel):
    """Site update request — all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    site_type: Optional[str] = Field(None)
    active: Optional[bool] = None
    currency: Optional[str] = Field(None, max_length=3)
    timezone: Optional[str] = None
    language: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None
    url: Optional[str] = None
    logo_url: Optional[str] = None
    primary_billing_address: Optional[Dict[str, Any]] = None
    primary_shipping_address: Optional[Dict[str, Any]] = None
    shipping_addresses: Optional[List[Dict[str, Any]]] = None
    geo: Optional[Dict[str, Any]] = None
    external_id: Optional[str] = None
    is_headquarter: Optional[bool] = None


class StoreUpdateRequest(BaseModel):
    """Store update request — all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    store_type: Optional[str] = None
    active: Optional[bool] = None
    site_id: Optional[str] = None
    currency: Optional[str] = Field(None, max_length=3)
    timezone: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    url: Optional[str] = None
    logo_url: Optional[str] = None
    primary_shipping_address: Optional[Dict[str, Any]] = None
    pickup_address: Optional[Dict[str, Any]] = None
    geo: Optional[Dict[str, Any]] = None
    external_id: Optional[str] = None
    fulfillment_mode: Optional[str] = None
    inventory_policy: Optional[str] = None


class UserUpdateRequest(BaseModel):
    """User update request — all fields optional"""
    first_name: Optional[str] = Field(None, min_length=1, max_length=255)
    last_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = None
    position: Optional[str] = None
    profile_image: Optional[str] = None
    home_site_id: Optional[str] = None
    home_store_id: Optional[str] = None
    home_org_unit_id: Optional[str] = None
    all_locations: Optional[bool] = None
    is_active: Optional[bool] = None


class VendorUpdateRequest(BaseModel):
    """Vendor update request — all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    contact_email: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = None
    # Integration fields
    preferred_protocol: Optional[str] = Field(None, description="api | cxml | edi | email")
    api_endpoint_url: Optional[str] = None
    cxml_endpoint_url: Optional[str] = None
    edi_partner_id: Optional[str] = None
    notification_email: Optional[str] = None
    webhook_url: Optional[str] = None
    onboarding_status: Optional[str] = None
    payment_terms: Optional[str] = None
    return_policy: Optional[str] = None
    lead_time_days: Optional[int] = Field(None, ge=0)
    minimum_order_minor: Optional[int] = Field(None, ge=0)
    tax_id: Optional[str] = None
    duns_number: Optional[str] = None


class CostCentreUpdateRequest(BaseModel):
    """Cost centre update request — all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    owner_user_id: Optional[str] = None
    is_active: Optional[bool] = None


class TokenExchangeRequest(BaseModel):
    """Request to exchange an external Azure AD / CIAM token for an internal JWT.

    Include ``invitation_token`` when accepting a tenant admin invitation.
    Omit it for self-onboarding (tenant admin's first sign-in).
    """
    azure_token: str = Field(..., description="Azure AD / CIAM access or ID token")
    invitation_token: Optional[str] = Field(None, description="Invitation token from email (only for invited users)")


class InvitationRequest(BaseModel):
    """Create an invitation for a user to join the tenant."""
    email: EmailStr = Field(..., description="Email address to invite")
    role_code: Optional[str] = Field(None, description="Role code to assign on acceptance")


class InvitationResponse(BaseModel):
    invitation_id: str
    tenant_id: str
    email: str
    status: str
    role_code: Optional[str] = None
    expires_at: str
    created_at: str


class InvitationListResponse(BaseModel):
    invitations: List[InvitationResponse]


class FeatureLimitStatus(BaseModel):
    """Per-feature usage snapshot returned at sign-in."""
    code: str
    name: str
    limit: Optional[int] = None
    used: int = 0
    remaining: Optional[int] = None
    reset_period: str = "none"
    resets_at: Optional[str] = None
    exceeded: bool = False


class SubscriptionContext(BaseModel):
    """Subscription info included in sign-in response."""
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    billing_cycle: Optional[str] = None
    is_active: bool = False
    is_trial: bool = False
    trial_ends_at: Optional[str] = None
    current_period_end: Optional[str] = None
    features: Optional[List[str]] = None
    feature_limits: Optional[List[FeatureLimitStatus]] = None
    any_limit_exceeded: bool = False


class TenantContext(BaseModel):
    """Resolved tenant info returned at sign-in."""
    tenant_id: str
    tenant_name: str
    tenant_type: str
    default_currency: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    industry: Optional[str] = None
    logo: Optional[str] = None
    is_active: bool = True


class BalanceContext(BaseModel):
    """Financial balance snapshot for the user's cost centres."""
    total_budget_minor: int = 0
    total_committed_minor: int = 0
    total_spent_minor: int = 0
    total_available_minor: int = 0
    currency: Optional[str] = None


class RBACContext(BaseModel):
    """Roles, permissions, and feature flags for the signed-in user."""
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    feature_flags: List[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    """Login response — full status check on every sign-in."""
    user_id: str
    tenant_id: str
    email: str
    display_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    last_login_at: Optional[str] = None
    token: str
    expiring_at: datetime
    refresh_token: Optional[str] = None
    subscription: Optional[SubscriptionContext] = None
    tenant: Optional[TenantContext] = None
    balance: Optional[BalanceContext] = None
    rbac: Optional[RBACContext] = None


# ── Mandate schemas ──────────────────────────────────────────────

class MandateCreateRequest(BaseModel):
    """Step 1: create a billing mandate before any tenant data is persisted.

    Trial is mandatory (7 days) and cannot be bypassed — the ``is_trial``
    field is accepted for backwards compatibility but always forced to True.

    Authentication is now Azure AD / CIAM token-driven — no password required.
    """
    email: EmailStr = Field(..., description="Tenant primary email")
    tenant_name: str = Field(min_length=1, max_length=200)
    tenant_type: str = Field(default="retailer")
    admin_email: EmailStr
    admin_firstname: str = Field(min_length=1, max_length=150)
    admin_lastname: str = Field(min_length=1, max_length=150)
    plan_code: str = Field(..., description="Subscription plan code")
    billing_cycle: str = Field(default="monthly")
    is_trial: bool = Field(
        default=True,
        description="Always True — 7-day trial is mandatory and non-bypassable",
    )
    phone: Optional[str] = None
    default_currency: Optional[str] = "GBP"
    timezone: Optional[str] = "UTC"
    locale: Optional[str] = "en_GB"
    industry: Optional[str] = None
    registration_number: Optional[str] = None
    billing_address: Optional[str] = None
    primary_domain: Optional[str] = None
    billing_email: Optional[EmailStr] = None
    tech_contact_email: Optional[EmailStr] = None
    support_contact_email: Optional[EmailStr] = None

    @field_validator('is_trial')
    @classmethod
    def enforce_mandatory_trial(cls, v):
        """Trial is non-bypassable — always return True regardless of input."""
        return True


class MandateResponse(BaseModel):
    mandate_id: str
    status: str
    stripe_customer_id: Optional[str] = None
    client_secret: Optional[str] = None


class MandateActivateRequest(BaseModel):
    """Step 2: activate the mandate (triggers tenant + user creation)."""
    mandate_id: str = Field(..., description="Mandate UUID from step 1")


class MandateActivateResponse(BaseModel):
    tenant_id: str
    mandate_id: str
    status: str
    subscription: Optional[SubscriptionContext] = None


class RefreshJwtRequest(BaseModel):
    user_id: str = Field(..., description="User id associated with the refresh token")
    refresh_token: str = Field(..., description="Refresh token string returned at login")


class RefreshJwtResponse(BaseModel):
    token: str
    expiring_at: str
    refresh_token: Optional[str] = None
    refresh_token_expires_at: Optional[str] = None
    roles: Optional[List[str]] = None


class SubscriptionPlanRequest(BaseModel):
    """Subscription plan creation request"""
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    created_by: Optional[str] = Field(default="zeroque_admin", max_length=100)
    price_monthly_minor: int = Field(ge=0)
    currency: str = Field(default="GBP", max_length=3)
    quarterly_discount_pct: float = Field(default=5.0, ge=0, le=100)
    yearly_discount_pct: float = Field(default=10.0, ge=0, le=100)


class FeatureRequest(BaseModel):
    """Feature creation request"""
    code: str = Field(min_length=1, max_length=50, description="Unique feature code")
    name: str = Field(min_length=1, max_length=100, description="Feature name")
    description: Optional[str] = Field(None, max_length=500, description="Feature description (optional)")
    cluster: Optional[str] = Field(None, max_length=50, description="Feature category (optional)")
    usage_type: str = Field(default="count", description="Usage type: count, gauge, etc.")
    max_unit: Optional[str] = Field(None, description="Unit label (optional)")
    reset_period: str = Field(default="monthly", description="Reset period: daily, weekly, monthly, yearly")


class TenantSubscriptionRequest(BaseModel):
    """Tenant subscription creation request"""
    tenant_id: str = Field(description="Tenant ID")
    plan_code: str = Field(description="Plan code")
    payment_method: str = Field(default="card", description="Payment method")
    current_period_end: Optional[datetime] = Field(None, description="Current period end date (optional)")
    current_period_start: Optional[datetime] = Field(None, description="Current period start date (optional)")
    external_id: Optional[str] = Field(None, description="External reference ID (optional)")
    previous_sub_id: Optional[int] = Field(None, description="Previous subscription ID (optional)")


class TenantSubscriptionUpgradeRequest(BaseModel):
    """Tenant subscription creation request"""
    tenant_id: str = Field(description="Tenant ID")
    subscription_id: int = Field(description="Subscription ID")
    upgrade_plan_code: str = Field(description="Plan code")


class UpgradePreviewResponse(BaseModel):
    current_plan: str
    new_plan: str
    remaining_days: int
    prorated_amount: float
    next_cycle_amount: float


class CurrentSubscriptionResponse(BaseModel):
    """Current subscription response"""
    tenant_id: str
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    on_trial: bool = False
    days_remaining: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CancelSubscriptionRequest(BaseModel):
    """Cancel subscription request"""
    tenant_id: str = Field(description="Tenant ID")
    subscription_id: int = Field(None, description="Subscription ID (optional)")
    reason: Optional[str] = Field(None, description="Cancellation reason")
    cancel_immediately: bool = Field(default=False, description="Cancel immediately or at period end")


class FeatureUsage(BaseModel):
    """Feature usage tracking for entitlement enforcement"""
    code: str
    name: str
    limit: Optional[int] = None  # None = unlimited
    used: int = 0
    remaining: Optional[int] = None  # None = unlimited
    reset_period: str = "none"  # daily, weekly, monthly, yearly, none
    resets_at: Optional[datetime] = None
    usage_type: str = "count"  # count, boolean

    model_config = ConfigDict(arbitrary_types_allowed=True)


class UserContext(BaseModel):
    user_id: str
    tenant_id: str
    roles: List[str]
    permissions: Dict[str, List[Dict[str, Optional[str]]]]
    manager_of: List[str] = Field(default_factory=list)
    raw_claims: Dict[str, Any] = Field(default_factory=dict)

    # Plan and feature entitlements
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    subscription_active: bool = False
    features: Dict[str, FeatureUsage] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def can_use_feature(self, feature_code: str, count: int = 1) -> bool:
        """Quick check if tenant can use a feature"""
        if not self.subscription_active:
            return False
        if feature_code not in self.features:
            return False
        feature = self.features[feature_code]
        if feature.limit is None:
            return True  # Unlimited
        return (feature.remaining or 0) >= count

    def get_feature_limit(self, feature_code: str) -> Optional[int]:
        """Get the limit for a feature, None if unlimited or not available"""
        if feature_code not in self.features:
            return 0  # Not in plan
        return self.features[feature_code].limit


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

    # Relationships
    vendor_id: Optional[str] = Field(None, description="Vendor ID (optional)")
    category_id: Optional[str] = Field(None, description="Category ID (optional)")
    brand_id: Optional[str] = Field(None, description="Brand ID (optional)")

    # Identity fields
    external_id: Optional[str] = Field(None, max_length=100, description="External system ID (NetSuite, etc.)")
    sku: str = Field(min_length=1, max_length=100, description="Product SKU")
    ean: Optional[str] = Field(None, max_length=128, description="European Article Number / barcode")
    mpn: Optional[str] = Field(None, max_length=100, description="Manufacturer Part Number")
    manufacturer: Optional[str] = Field(None, max_length=255, description="Manufacturer name")

    # Matrix (variant) fields
    is_matrix_item: bool = Field(default=False, description="TRUE if product has colour/size/fit variants")
    matrix_type: str = Field(default="standalone", description="standalone / parent / child")
    matrix_parent_id: Optional[str] = Field(None, description="Parent product ID for child variants")
    colour_id: Optional[str] = Field(None, description="Colour ID (optional)")
    size_id: Optional[str] = Field(None, description="Size ID (optional)")
    fit_id: Optional[str] = Field(None, description="Fit ID (optional)")
    item_option: Optional[str] = Field(None, max_length=255, description="Domain-specific option (Glove Type, etc.)")

    # Description fields
    display_name: str = Field(min_length=1, max_length=255, description="Primary display name in UI")
    web_display_name: Optional[str] = Field(None, max_length=255, description="E-commerce display name (max 60 char)")
    sales_description: Optional[str] = Field(None, description="Customer-facing description")
    purchase_description: Optional[str] = Field(None, description="Supplier-facing description")
    packing_slip_description: Optional[str] = Field(None, description="Logistics/packing slip text")
    detailed_description: Optional[str] = Field(None, description="Extended/HTML product description")
    additional_description: Optional[str] = Field(None, description="Supplementary information")

    # Physical attributes
    weight: Optional[float] = Field(None, description="Product weight value")
    weight_unit: Optional[str] = Field(None, max_length=10, description="g / kg / lb")
    width: Optional[float] = Field(None, description="Width in mm")
    depth: Optional[float] = Field(None, description="Depth in mm")
    height: Optional[float] = Field(None, description="Height in mm")

    # Packaging
    outer_quantity: Optional[int] = Field(None, description="Quantity in outer packaging")
    outer_label_id: Optional[int] = Field(None, description="Outer UOS label ID")
    inner_quantity: Optional[int] = Field(None, description="Quantity in inner packaging")
    inner_label_id: Optional[int] = Field(None, description="Inner UOS label ID")
    reorder_multiple: Optional[int] = Field(None, description="Minimum reorder multiple")

    # Pricing
    purchase_price_minor: int = Field(ge=0, description="Cost price in pence/cents (minor units)")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")
    tax_rate: int = Field(default=0, ge=0, description="Tax rate in basis points")

    # Classification
    manufacturer_country: Optional[str] = Field(None, max_length=100, description="Country of origin")
    commodity_code: Optional[str] = Field(None, max_length=50, description="HS/customs commodity code")
    product_type: Optional[str] = Field(None, max_length=50, description="Product type classification")

    # Web / filtering
    colour_filter: Optional[str] = Field(None, max_length=100, description="Filterable colour value for web store")
    size_filter: Optional[str] = Field(None, max_length=100, description="Filterable size value for web store")
    search_keywords: Optional[str] = Field(None, description="SEO / site search keywords")

    # Hazmat fields
    is_dangerous_goods: bool = Field(default=False, description="Master dangerous goods flag")
    cas_number: Optional[str] = Field(None, max_length=50, description="Chemical Abstracts Service number")
    un_number: Optional[str] = Field(None, max_length=50, description="UN dangerous goods number")
    proper_shipping_name: Optional[str] = Field(None, max_length=255, description="Official shipping name for hazmat")
    transport_hazard_class: Optional[str] = Field(None, max_length=50, description="Hazmat transport class")
    packing_group: Optional[str] = Field(None, max_length=20, description="I / II / III")
    adr_classification_code: Optional[str] = Field(None, max_length=50, description="ADR road transport classification")
    adr_tunnel_restriction_code: Optional[str] = Field(None, max_length=20, description="Tunnel restriction code")
    adr_hazard_id_number: Optional[str] = Field(None, max_length=50, description="ADR hazard identification number")

    # System fields
    tax_code: Optional[str] = Field(None, max_length=64, description="Tax code reference")
    restricted: bool = Field(default=False, description="Restricted product flag")
    product_metadata: Optional[Dict[str, Any]] = Field(None, description="Flexible JSON for extra data")
    comments: Optional[str] = Field(None, description="Free-text notes/comments")


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


class StoreProductRequest(BaseModel):
    store_id: str
    product_id: str
    price_minor: int
    currency: str = "GBP"
    is_available: Optional[bool] = True
    stock_quantity: Optional[int] = 0
    low_stock_threshold: Optional[int] = 10



class CheckoutRequest(BaseModel):
    tenant_id: str
    stripe_customer_id: Optional[str] = None
    price_id: str | None = None
    amount: int = None
    quantity: int = 1
    currency: str = "usd"
    mode: str = "payment"
    billing_cycle: str = "monthly"
    plan_code: str


class VendorUserUpdate(BaseModel):
    email: Optional[str] = None
    password_hash: Optional[str] = None
    first_name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    vendor_id: Optional[uuid.UUID] = None


class VendorUserCreate(BaseModel):
    vendor_id: uuid.UUID
    password_hash: str
    email: EmailStr
    first_name: str
    role: str = "vendor_staff"
    active: bool = True


class SubscribeRequest(BaseModel):
    """Request to subscribe to a plan"""
    plan_code: str = Field(description="Plan code to subscribe to")
    billing_cycle: str = Field(default="monthly", description="monthly, quarterly, or yearly")
    start_trial: bool = Field(default=True, description="Start with 7-day free trial")


# ==================================================================================
# APPROVED RANGE SCHEMAS
# ==================================================================================

class ApprovedRangeCreateRequest(BaseModel):
    """Create an approved range"""
    name: str = Field(min_length=1, max_length=255, description="Range name")
    description: Optional[str] = Field(None, max_length=1000, description="Range description")
    is_universal: bool = Field(default=False, description="If true, applies to all org units")


class ApprovedRangeUpdateRequest(BaseModel):
    """Update an approved range"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Range name")
    description: Optional[str] = Field(None, max_length=1000, description="Range description")
    is_universal: Optional[bool] = Field(None, description="If true, applies to all org units")


class ApprovedRangeOrgUnitRequest(BaseModel):
    """Map approved range to org unit(s)"""
    org_unit_ids: List[str] = Field(min_length=1, description="List of org unit IDs to map")


class ApprovedRangeCategoryRequest(BaseModel):
    """Add category/ies to an approved range (PRIMARY governance path)"""
    category_ids: List[str] = Field(min_length=1, description="List of category IDs to include")
    include_subcategories: bool = Field(default=True, description="If True, subcategories are also included")


# ==================================================================================
# FINANCIAL CALENDAR SCHEMAS
# ==================================================================================

class FinancialCalendarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    calendar_type: str = Field(default="gregorian", description="gregorian | 445 | 454 | 444 | custom")
    start_month: int = Field(default=1, ge=1, le=12, description="First month of the financial year (1=Jan)")
    currency: Optional[str] = Field("GBP", max_length=3)
    is_default: bool = Field(default=False)

    @field_validator("calendar_type")
    @classmethod
    def validate_calendar_type(cls, v):
        allowed = {"gregorian", "445", "454", "444", "custom"}
        if v not in allowed:
            raise ValueError(f"calendar_type must be one of {allowed}")
        return v


class FinancialCalendarUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class FinancialYearCreate(BaseModel):
    label: str = Field(min_length=1, max_length=50, description="e.g. 'FY2025' or 'FY2025-Part1'")
    start_date: date
    end_date: date
    year_type: str = Field(default="full", description="full | part | adjusted")
    total_budget_minor: Optional[int] = Field(None, ge=0, description="Optional company-wide cap for this year")
    notes: Optional[str] = None

    @field_validator("year_type")
    @classmethod
    def validate_year_type(cls, v):
        if v not in {"full", "part", "adjusted"}:
            raise ValueError("year_type must be full | part | adjusted")
        return v


class PeriodGenerationRequest(BaseModel):
    """Ask the system to auto-generate FinancialPeriod rows for a FinancialYear."""
    period_type: str = Field(default="month", description="month | quarter | week")

    @field_validator("period_type")
    @classmethod
    def validate_period_type(cls, v):
        if v not in {"month", "quarter", "week"}:
            raise ValueError("period_type must be month | quarter | week")
        return v


class FinancialPeriodCreate(BaseModel):
    """Manually create a single FinancialPeriod (for custom calendars)."""
    period_number: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=50)
    period_type: str = Field(default="month")
    start_date: date
    end_date: date


# ==================================================================================
# BUDGET SCHEMAS
# ==================================================================================

class CompanyBudgetCapCreate(BaseModel):
    year_id: str = Field(description="FinancialYear UUID")
    calendar_id: str = Field(description="FinancialCalendar UUID")
    currency: str = Field(default="GBP", max_length=3)
    total_budget_minor: int = Field(ge=0, description="Total company budget in minor units")
    hard_cap: bool = Field(default=False, description="If True, system blocks any breach")
    notes: Optional[str] = None


class CompanyBudgetCapUpdate(BaseModel):
    total_budget_minor: Optional[int] = Field(None, ge=0)
    hard_cap: Optional[bool] = None
    notes: Optional[str] = None
    override_reason: Optional[str] = Field(None, description="Required when soft-cap is breached")


class CCBudgetVersionCreate(BaseModel):
    cost_centre_id: str
    year_id: str
    period_id: Optional[str] = Field(None, description="NULL = annual allocation")
    currency: str = Field(default="GBP", max_length=3)
    budget_minor: int = Field(ge=0)
    override_reason: Optional[str] = None


class CCBudgetVersionUpdate(BaseModel):
    budget_minor: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    override_reason: Optional[str] = None


class BudgetReallocationRequest(BaseModel):
    """Transfer or add budget between two CC versions."""
    source_version_id: Optional[str] = Field(None, description="NULL for additive top-up from central pool")
    target_version_id: str
    amount_minor: int = Field(gt=0)
    note: Optional[str] = None


class BringForwardRequest(BaseModel):
    """Pull future-period budget into current period."""
    cost_centre_id: str
    from_version_id: str = Field(description="Future period CC budget version UUID")
    to_version_id: str = Field(description="Current period CC budget version UUID")
    amount_minor: int = Field(gt=0)
    justification: str = Field(min_length=5, max_length=1000)


class BudgetChangeDecision(BaseModel):
    decision: str = Field(description="approved | rejected")
    note: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v):
        if v not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        return v


# ==================================================================================
# USER BUDGET SCHEMAS
# ==================================================================================

class UserCCAssignmentCreate(BaseModel):
    user_id: str
    cost_centre_id: str
    is_primary: bool = Field(default=False)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class UserBudgetLimitCreate(BaseModel):
    user_id: str
    cost_centre_id: str
    year_id: str
    period_id: Optional[str] = None
    limit_type: str = Field(description="requester | approver")
    window_type: str = Field(description="transaction | week | month | quarter | year")
    limit_amount_minor: int = Field(ge=0, description="0 = always requires approval")
    carry_forward_enabled: bool = Field(default=False)
    window_start: Optional[date] = None
    window_end: Optional[date] = None

    @field_validator("limit_type")
    @classmethod
    def validate_limit_type(cls, v):
        if v not in {"requester", "approver"}:
            raise ValueError("limit_type must be 'requester' or 'approver'")
        return v

    @field_validator("window_type")
    @classmethod
    def validate_window_type(cls, v):
        if v not in {"transaction", "week", "month", "quarter", "year"}:
            raise ValueError("window_type must be transaction | week | month | quarter | year")
        return v


class UserBudgetLimitUpdate(BaseModel):
    limit_amount_minor: Optional[int] = Field(None, ge=0)
    carry_forward_enabled: Optional[bool] = None
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    is_active: Optional[bool] = None


# ==================================================================================
# APPROVAL POLICY SCHEMAS
# ==================================================================================

class StageConditionCreate(BaseModel):
    field: str = Field(description="amount | cost_centre | category | vendor")
    operator: str = Field(description="gte | lte | eq | in | neq")
    value: Any = Field(description="Scalar or list value to compare against")
    logic: str = Field(default="AND", description="AND | OR (how this condition combines with others)")

    @field_validator("logic")
    @classmethod
    def validate_logic(cls, v):
        if v not in {"AND", "OR"}:
            raise ValueError("logic must be AND or OR")
        return v


class StageApproverCreate(BaseModel):
    approver_type: str = Field(
        description="user | org_unit_manager | hierarchy_traversal | role"
    )
    approver_user_id: Optional[str] = None
    org_unit_id: Optional[str] = None
    role_code: Optional[str] = None


class ApprovalStageCreate(BaseModel):
    stage_order: int = Field(ge=1)
    name: Optional[str] = None
    parallel_allowed: bool = Field(default=False)
    min_approvers: int = Field(default=1, ge=1)
    escalation_timeout_hours: Optional[int] = Field(None, ge=1)
    conditions: List[StageConditionCreate] = Field(default_factory=list)
    approvers: List[StageApproverCreate] = Field(default_factory=list)


class ApprovalPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    cost_centre_id: Optional[str] = Field(None, description="NULL = tenant-wide policy")
    routing_mode: str = Field(default="hierarchical", description="broadcast | hierarchical")
    broadcast_n: int = Field(default=3, ge=1)
    sox_sod_enforced: bool = Field(default=True)
    partial_approval_mode: str = Field(default="block", description="block | partial | force_top_up")
    zero_value_mode: str = Field(default="auto", description="auto | require_approval")
    stages: List[ApprovalStageCreate] = Field(default_factory=list)

    @field_validator("routing_mode")
    @classmethod
    def validate_routing_mode(cls, v):
        if v not in {"broadcast", "hierarchical"}:
            raise ValueError("routing_mode must be broadcast or hierarchical")
        return v


# ==================================================================================
# PURCHASE REQUEST SCHEMAS
# ==================================================================================

class PurchaseRequestCreate(BaseModel):
    cost_centre_id: str
    vendor_id: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="[{product_id, qty, unit_price_minor, description}]"
    )
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="GBP", max_length=3)
    notes: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(description="approve | reject | escalate")
    note: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v):
        if v not in {"approve", "reject", "escalate"}:
            raise ValueError("decision must be approve | reject | escalate")
        return v


class PurchaseRequestResponse(BaseModel):
    request_id: str
    tenant_id: str
    requester_id: str
    cost_centre_id: str
    amount_minor: int
    currency: str
    status: str
    approval_mode: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)



