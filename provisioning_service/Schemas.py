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
    """User creation request"""
    tenant_id: str = Field(..., description="Tenant ID (UUID)")
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., description="Password hash")
    first_name: str = Field(..., min_length=1, max_length=255, description="First name")
    last_name: str = Field(..., min_length=1, max_length=255, description="Last name")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
    position: Optional[str] = Field(None, description="Position / job title (optional)")
    profile_image: Optional[str] = Field(None, description="Profile image URL (optional)")
    is_sso_enabled: Optional[bool] = Field(False, description="Is SSO enabled (optional)")
    home_site_id: Optional[str] = Field(None, description="Home site ID (UUID, optional)")
    home_store_id: Optional[str] = Field(None, description="Home store ID (UUID, optional)")
    home_org_unit_id: Optional[str] = Field(None, description="Home org unit ID (UUID, optional)")
    all_locations: Optional[bool] = Field(False, description="Access to all locations (optional)")

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


class LoginRequest(BaseModel):
    """Login request"""
    email: EmailStr = Field(description="User email")
    password: str = Field(description="User password")


class LoginResponse(BaseModel):
    """Login response"""
    user_id: str
    tenant_id: str
    email: str
    display_name: str
    last_login_at: Optional[str] = None
    token: str
    expiring_at: datetime
    refresh_token: Optional[str] = None


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


class ResetPasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=8)
    new_password: str = Field(..., min_length=8)

    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)

    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v


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

