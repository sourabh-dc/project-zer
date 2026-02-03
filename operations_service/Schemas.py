import uuid
from datetime import datetime, date
from pydantic import field_validator, BaseModel, Field, EmailStr, ConfigDict, constr
from typing import Optional, Dict, List, Tuple, Any
import re

# ==================================================================================
# REQUEST/RESPONSE MODELS
# ==================================================================================
class TenantRequest(BaseModel):
    """Tenant creation request"""
    name: str = Field(min_length=1, max_length=200, description="Company name")
    type: str = Field(description="Tenant type: customer, retailer, or distributor")
    registration_number: Optional[str] = Field(None, max_length=100, description="Registration number (optional)")
    email: EmailStr = Field(..., description="Administrative contact email")
    admin_firstname: str = Field(min_length=1, max_length=150, description="Admin first name")
    admin_lastname: str = Field(min_length=1, max_length=150, description="Admin last name")
    password: str = Field(min_length=8, max_length=128, description="Admin password (min 8 chars)")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")

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


class StoreRequest(BaseModel):
    """Store creation request"""
    name: str = Field(min_length=1, max_length=255, description="Store name")
    type: str = Field(description="Store type")
    site_id: str = Field(description="Site ID")
    tenant_id: str = Field(description="Tenant ID")
    geo: Optional[Dict] = Field(None, description="Geographic metadata (optional)")


# Add to Schemas.py

class UserRequest(BaseModel):
    """User creation request"""
    email: EmailStr = Field(description="Valid email address")
    first_name: str = Field(min_length=1, max_length=255, description="Display name")
    last_name: str = Field(min_length=1, max_length=255, description="Display name")
    tenant_id: str = Field(description="Tenant ID")
    phone: Optional[str] = Field(None, description="Contact phone number (E.164 or digits)")
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

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return v
        if not re.match(r'^\+?\d{7,15}$', v):
            raise ValueError('Phone must be digits, optionally starting with + and 7-15 characters long')
        return v


class SuperUserRequest(BaseModel):
    """Super user creation request for a tenant"""
    email: EmailStr = Field(description="Valid email address for super user")
    display_name: str = Field(min_length=1, max_length=255, description="Display name")
    password: Optional[str] = Field(None, min_length=8, max_length=128, description="Password (optional, auto-generated if not provided)")
    
    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password strength if provided"""
        if v is None:
            return v
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
    code: str = Field(min_length=1, max_length=100, description="Role code (required)")
    description: Optional[str] = Field(None, max_length=500, description="Role description (optional)")


class VendorRequest(BaseModel):
    tenant_id: str = Field(description="Tenant ID")
    """Vendor creation request"""
    name: str = Field(min_length=1, max_length=255, description="Vendor name")
    contact_email: Optional[EmailStr] = Field(None, description="Contact email (optional)")
    description: Optional[str] = Field(None, max_length=500, description="Description (optional)")


class CostCentreRequest(BaseModel):
    """Cost centre creation request"""
    name: str = Field(min_length=1, max_length=200, description="Cost centre name")
    budget_minor: int = Field(ge=0, description="Budget in minor units (required)")
    manager_user_id: Optional[str] = Field(None, description="Manager user ID (optional)")
    tenant_id: str = Field(description="Tenant ID")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")


class OrgUnitRequest(BaseModel):
    """Organizational unit creation request"""
    name: str = Field(min_length=1, max_length=255, description="Org unit name")
    type: str = Field(min_length=1, max_length=50, description="Type: directorate, business_unit, department, team, etc.")
    tenant_id: str = Field(description="Tenant ID")
    parent_org_unit_id: Optional[str] = Field(None, description="Parent org unit ID (optional)")


class OrgUnitAssignmentRequest(BaseModel):
    """User to org unit assignment request"""
    role_id: str = Field(description="Role ID for this assignment")


class PasswordResetRequest(BaseModel):
    """Password reset request"""
    new_password: str = Field(min_length=8, max_length=128, description="New password (min 8 chars)")
    
    @field_validator('new_password')
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


class PlanFeatureRequest(BaseModel):
    """Plan-feature association request"""
    plan_code: str = Field(description="Plan code")
    feature_code: str = Field(description="Feature code")


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


class UpgradeDowngradeRequest(BaseModel):
    """Upgrade or downgrade subscription request"""
    new_plan_code: str = Field(description="New plan code")
    apply_immediately: bool = Field(default=False, description="Apply immediately or at period end")


class CheckEntitlementRequest(BaseModel):
    """Check entitlement request"""
    tenant_id: str = Field(description="Tenant ID")
    feature_code: str = Field(description="Feature code to check")
    requested_count: Optional[int] = Field(default=1, ge=1, description="Requested usage count for pre-check")


class RecordUsageRequest(BaseModel):
    """Record usage request"""
    tenant_id: str = Field(description="Tenant ID")
    feature_code: str = Field(description="Feature code")
    usage_type: str = Field(description="Usage type identifier")
    count: int = Field(default=1, ge=1, description="Usage count")


class ShoppingRequest(BaseModel):
    """Shopping purchase request"""
    user_id: str = Field(description="User ID making purchase")
    cost_centre_id: str = Field(description="Cost centre ID")
    amount_minor: int = Field(ge=1, description="Purchase amount in minor units")
    currency: str = Field(default="GBP", description="Currency code")
    description: str = Field(description="Purchase description")
    order_id: Optional[str] = Field(None, description="Order ID (optional)")
    force_allow: bool = Field(default=False, description="Force allow even if blocked")


class ShoppingResponse(BaseModel):
    """Shopping purchase response"""
    event_id: str
    user_id: str
    amount_minor: int
    allocated_budget_minor: int
    spent_minor: int
    remaining_minor: int
    is_overspend: bool
    blocked_from_shopping: bool
    message: str


class AssignRoleRequest(BaseModel):
    """Assign role to user request"""
    role_code: str = Field(description="Role ID to assign")


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
    vendor_id: Optional[str] = Field(None, description="Vendor ID (optional)")
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


class PricebookRequest(BaseModel):
    """Pricebook creation request"""
    store_id: str = Field(description="Store ID")
    name: str = Field(min_length=1, max_length=255, description="Pricebook name")
    description: Optional[str] = Field(None, max_length=500, description="Description (optional)")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")


class PriceRuleRequest(BaseModel):
    """Price rule creation request"""
    product_id: Optional[str] = Field(None, description="Product ID (optional, null = applies to all)")
    variant_id: Optional[str] = Field(None, description="Variant ID (optional)")
    rule_type: str = Field(description="Rule type: fixed, percentage, discount")
    rule_value: int = Field(description="For fixed: price in minor units, for percentage: basis points (1000 = 10%)")
    min_quantity: Optional[int] = Field(None, ge=1, description="Min quantity for rule to apply (optional)")
    max_quantity: Optional[int] = Field(None, ge=1, description="Max quantity for rule to apply (optional)")
    valid_from: Optional[datetime] = Field(None, description="Valid from date (optional)")
    valid_until: Optional[datetime] = Field(None, description="Valid until date (optional)")

    @field_validator('rule_type')
    @classmethod
    def validate_rule_type(cls, v):
        if v not in ['fixed', 'percentage', 'discount']:
            raise ValueError('Rule type must be one of: fixed, percentage, discount')
        return v


class PriceCalculationRequest(BaseModel):
    """Price calculation request"""
    product_id: str = Field(description="Product ID")
    variant_id: Optional[str] = Field(None, description="Variant ID (optional)")
    pricebook_id: str = Field(description="Pricebook ID")
    quantity: int = Field(default=1, ge=1, description="Quantity")


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
    total_amount_minor: Optional[int] = Field(None, description="Amount in minor units (optional)")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")
    due_date: Optional[datetime] = Field(None, description="Due date (optional)")
    
    @field_validator('total_amount_minor')
    @classmethod
    def validate_amount(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Amount must be positive")
        return v


class ApprovalResponseRequest(BaseModel):
    """Approval response request"""
    approver_user_id: str = Field(description="Approver user ID")
    approved: bool = Field(description="Whether to approve or deny")
    notes: Optional[str] = Field(None, max_length=500, description="Approval notes (optional)")

class ResourceContext(BaseModel):
    resource_type: str
    resource_id: Optional[str] = None
    parent_chain: List[Tuple[str, str]] = Field(default_factory=list)


class UserContext(BaseModel):
    user_id: str
    tenant_id: str
    roles: List[str]
    permissions: Dict[str, List[Dict[str, Optional[str]]]]
    manager_of: List[str] = Field(default_factory=list)
    raw_claims: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

# New Code- Sebin

class PaymentIntentRequest(BaseModel):
    """Request model for creating payment intents"""
    tenant_id: str = Field(..., description="Tenant ID")
    order_id: Optional[str] = Field(None, description="Associated order ID")
    amount_minor: int = Field(..., description="Amount in minor units")
    currency: str = Field(default="GBP", description="Currency code")
    provider: str = Field(default="stripe", description="Payment provider")
    site_id: Optional[str] = Field(None, description="Site ID")
    store_id: Optional[str] = Field(None, description="Store ID")
    user_id: Optional[str] = Field(None, description="User ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class CustomerRequest(BaseModel):
    """Request model for customer operations"""
    tenant_id: str = Field(..., description="Tenant ID")
    provider: str = Field(default="stripe", description="Payment provider")
    email: Optional[str] = Field(None, description="Customer email")
    name: Optional[str] = Field(None, description="Customer name")
    phone: Optional[str] = Field(None, description="Customer phone")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class RefundRequest(BaseModel):
    """Request model for payment refunds"""
    tenant_id: str = Field(..., description="Tenant ID")
    payment_intent_id: str = Field(..., description="Payment intent ID")
    amount_minor: Optional[int] = Field(None, description="Refund amount in minor units")
    reason: Optional[str] = Field(None, description="Refund reason")


class PaymentAdjustmentRequest(BaseModel):
    """Request model for payment adjustments"""
    tenant_id: str = Field(..., description="Tenant ID")
    payment_intent_id: str = Field(..., description="Payment intent ID")
    adjustment_type: str = Field(..., description="Type of adjustment")
    amount_minor: int = Field(..., description="Adjustment amount in minor units")
    currency: str = Field(default="GBP", description="Currency code")
    reason: Optional[str] = Field(None, description="Adjustment reason")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class TradeAccountRequest(BaseModel):
    """Trade account creation request"""
    company_name: str = Field(..., description="Company name", max_length=200)
    contact_email: str = Field(..., description="Contact email", max_length=255)
    credit_limit_minor: int = Field(..., description="Credit limit in minor units", ge=0)
    currency: str = Field("GBP", description="Currency code", max_length=3)
    payment_terms_days: int = Field(30, description="Payment terms in days", ge=0)


class TradeAccountResponse(BaseModel):
    """Trade account response model"""
    trade_account_id: str
    account_number: str
    company_name: str
    contact_email: str
    credit_limit_minor: int
    available_credit_minor: int
    currency: str
    payment_terms_days: int
    is_active: bool
    created_at: datetime


class PaymentIntentResponse(BaseModel):
    """Payment intent response model"""
    payment_intent_id: str
    client_secret: str
    amount_minor: int
    currency: str
    status: str
    provider: str
    expires_at: Optional[datetime]


class MultiCurrencyConversionRequest(BaseModel):
    """Currency conversion request"""
    from_currency: str = Field(..., description="Source currency", max_length=3)
    to_currency: str = Field(..., description="Target currency", max_length=3)
    amount_minor: int = Field(..., description="Amount in minor units", gt=0)


class MultiCurrencyConversionResponse(BaseModel):
    """Currency conversion response"""
    from_currency: str
    to_currency: str
    original_amount_minor: int
    converted_amount_minor: int
    exchange_rate: float
    converted_at: datetime

class OrderRequest(BaseModel):
    """Order creation request"""
    customer_id: str
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    order_type: str = "purchase"
    items: List[Dict[str, Any]]
    shipping_address: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class OrderItemRequest(BaseModel):
    """Order item request"""
    product_id: str
    variant_id: Optional[str] = None
    quantity: int
    unit_price_minor: int


class OrderUpdateRequest(BaseModel):
    """Order update request"""
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class BaseBillingRequest(BaseModel):
    """Base request model with common fields"""
    tenant_id: str = Field(..., description="Tenant ID for multi-tenancy")

    @field_validator('tenant_id')
    @classmethod
    def validate_tenant_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('tenant_id must be a valid UUID')


class InvoiceLineRequest(BaseModel):
    """Request model for invoice line items"""
    line_number: int = Field(..., description="Line number", ge=1)
    description: str = Field(..., description="Line item description", max_length=255)
    quantity: int = Field(..., description="Quantity", gt=0)
    unit_price_minor: int = Field(..., description="Unit price in minor units", ge=0)
    tax_minor: int = Field(0, description="Tax amount in minor units", ge=0)
    tax_code: Optional[str] = Field(None, description="Tax code", max_length=20)

    @property
    def line_total_minor(self) -> int:
        return (self.quantity * self.unit_price_minor) + self.tax_minor


class CreateInvoiceRequest(BaseBillingRequest):
    """Request model for creating invoices"""
    invoice_number: Optional[str] = Field(None, description="Invoice number", max_length=50)
    currency: str = Field("GBP", description="Currency code", max_length=3)
    due_date: Optional[date] = Field(None, description="Due date")
    lines: List[InvoiceLineRequest] = Field(..., description="Invoice line items", min_items=1)
    ar_customer_code: Optional[str] = Field(None, description="AR customer code", max_length=100)
    terms: str = Field("NET30", description="Payment terms", max_length=20)

    @field_validator('lines')
    @classmethod
    def validate_lines(cls, v):
        if not v:
            raise ValueError('At least one line item is required')
        line_numbers = [line.line_number for line in v]
        if len(line_numbers) != len(set(line_numbers)):
            raise ValueError('Line numbers must be unique')
        return v

    @property
    def subtotal_minor(self) -> int:
        return sum(line.quantity * line.unit_price_minor for line in self.lines)

    @property
    def tax_total_minor(self) -> int:
        return sum(line.tax_minor for line in self.lines)

    @property
    def total_minor(self) -> int:
        return self.subtotal_minor + self.tax_total_minor


class InvoiceResponse(BaseModel):
    """Response model for invoices"""
    id: str
    tenant_id: str
    invoice_number: Optional[str]
    status: str
    amount_minor: int
    currency: str
    tax_total_minor: int
    subtotal_minor: int
    due_date: Optional[date]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    lines: List[Dict[str, Any]] = []

# Add to Schemas.py

class StoreProductRequest(BaseModel):
    store_id: str
    product_id: str
    price_minor: int
    currency: str = "GBP"
    is_available: Optional[bool] = True
    stock_quantity: Optional[int] = 0
    low_stock_threshold: Optional[int] = 10

class StoreProductResponse(BaseModel):
    id: str
    store_id: str
    product_id: str
    price_minor: int
    currency: str
    is_available: bool
    stock_quantity: int
    created_at: str
    
class SettlementItemRequest(BaseModel):
    """Request model for settlement items"""
    order_id: Optional[str] = Field(None, description="Order ID")
    sub_order_id: Optional[str] = Field(None, description="Sub-order ID")
    payout_amount_minor: int = Field(..., description="Payout amount in minor units", ge=0)
    commission_amount_minor: int = Field(..., description="Commission amount in minor units", ge=0)
    fee_amount_minor: int = Field(0, description="Fee amount in minor units", ge=0)
    notes: Optional[str] = Field(None, description="Item notes")

    @property
    def net_amount_minor(self) -> int:
        return self.payout_amount_minor - self.commission_amount_minor - self.fee_amount_minor


class CreateSettlementRequest(BaseBillingRequest):
    """Request model for creating vendor settlements"""
    vendor_id: str = Field(..., description="Vendor ID")
    settlement_period_start: date = Field(..., description="Settlement period start date")
    settlement_period_end: date = Field(..., description="Settlement period end date")
    currency: str = Field("GBP", description="Currency code", max_length=3)
    items: List[SettlementItemRequest] = Field(..., description="Settlement items", min_items=1)
    notes: Optional[str] = Field(None, description="Settlement notes")

    @field_validator('vendor_id')
    @classmethod
    def validate_vendor_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('vendor_id must be a valid UUID')


class SettlementResponse(BaseModel):
    """Response model for settlements"""
    settlement_id: str
    vendor_id: str
    tenant_id: str
    settlement_period_start: date
    settlement_period_end: date
    total_sales_minor: int
    total_commission_minor: int
    net_settlement_minor: int
    currency: str
    settlement_status: str
    settlement_date: Optional[datetime]
    created_at: datetime


class CreateDisputeRequest(BaseModel):
    """Request model for creating disputes"""
    tenant_id: str = Field(..., description="Tenant ID")
    settlement_id: Optional[str] = Field(None, description="Settlement ID")
    settlement_item_id: Optional[str] = Field(None, description="Settlement item ID")
    dispute_amount_minor: int = Field(..., description="Dispute amount in minor units", ge=0)
    dispute_reason: str = Field(..., description="Dispute reason", max_length=255)
    dispute_notes: Optional[str] = Field(None, description="Dispute notes")

    @field_validator('tenant_id', 'settlement_id', 'settlement_item_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError(f'Invalid UUID format: {v}')


class DisputeResponse(BaseModel):
    """Response model for disputes"""
    id: str
    settlement_id: Optional[str]
    settlement_item_id: Optional[str]
    tenant_id: str
    dispute_amount_minor: int
    dispute_reason: str
    dispute_status: str
    dispute_notes: Optional[str]
    created_at: datetime


class CreateAdjustmentRequest(BaseModel):
    """Request model for creating adjustments"""
    tenant_id: str = Field(..., description="Tenant ID")
    settlement_id: str = Field(..., description="Settlement ID")
    settlement_item_id: Optional[str] = Field(None, description="Settlement item ID")
    adjustment_amount_minor: int = Field(..., description="Adjustment amount in minor units")
    adjustment_reason: str = Field(..., description="Adjustment reason", max_length=255)
    adjustment_type: str = Field(..., description="Adjustment type",
                                 pattern="^(commission|chargeback|refund|bonus|penalty)$")
    currency: str = Field("GBP", description="Currency code", max_length=3)
    adjustment_notes: Optional[str] = Field(None, description="Adjustment notes")

    @field_validator('tenant_id', 'settlement_id', 'settlement_item_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError(f'Invalid UUID format: {v}')


class AdjustmentResponse(BaseModel):
    """Response model for adjustments"""
    id: str
    settlement_id: str
    settlement_item_id: Optional[str]
    tenant_id: str


class CostCentreResponse(BaseModel):
    """Cost centre response model - Phase 4"""
    cost_centre_id: str
    name: str
    code: str
    description: Optional[str]
    parent_cost_centre_id: Optional[str]
    budget_owner_id: str
    is_active: bool
    created_at: datetime


class BudgetRequest(BaseModel):
    """Budget creation request - Phase 4"""
    cost_centre_id: str = Field(..., description="Cost centre ID")
    budget_year: int = Field(..., description="Budget year", ge=2020, le=2030)
    budget_month: Optional[int] = Field(None, description="Budget month (1-12)", ge=1, le=12)
    budget_type: str = Field(..., description="Budget type", pattern="^(annual|monthly|project)$")
    budget_amount_minor: int = Field(..., description="Budget amount in minor units", gt=0)
    currency: str = Field("GBP", description="Currency code", max_length=3)
    approval_workflow_id: Optional[str] = Field(None, description="Approval workflow ID")


class BudgetResponse(BaseModel):
    """Budget response model - Phase 4"""
    budget_id: str
    cost_centre_id: str
    budget_year: int
    budget_month: Optional[int]
    budget_type: str
    budget_amount_minor: int
    spent_amount_minor: int
    available_amount_minor: int
    currency: str
    status: str
    created_at: datetime


class BudgetCheckRequest(BaseModel):
    """Budget check request - Phase 4"""
    cost_centre_id: str = Field(..., description="Cost centre ID")
    amount_minor: int = Field(..., description="Amount to check in minor units", gt=0)
    description: str = Field(..., description="Transaction description")
    reference_id: Optional[str] = Field(None, description="Reference ID (invoice, order, etc.)")
    reference_type: Optional[str] = Field(None, description="Reference type")


class BudgetCheckResponse(BaseModel):
    """Budget check response - Phase 4"""
    budget_id: str
    cost_centre_id: str
    requested_amount_minor: int
    available_amount_minor: int
    is_approved: bool
    approval_required: bool
    approval_id: Optional[str]
    message: str


class SpendRequest(BaseModel):
    """Spend recording request - Phase 4"""
    cost_centre_id: str = Field(..., description="Cost centre ID")
    amount_minor: int = Field(..., description="Spend amount in minor units", gt=0)
    description: str = Field(..., description="Spend description")
    reference_id: Optional[str] = Field(None, description="Reference ID")
    reference_type: Optional[str] = Field(None, description="Reference type")
    approval_id: Optional[str] = Field(None, description="Pre-approved approval ID")

class LedgerEntryRequest(BaseModel):
    """Request model for creating ledger entries"""
    tenant_id: str = Field(..., description="Tenant ID")
    account: str = Field(..., description="Account name")
    entry_type: str = Field(..., description="Entry type (debit/credit)")
    amount_minor: int = Field(..., description="Amount in minor units", gt=0)
    currency: str = Field(..., description="Currency code")
    cost_centre_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")

    @field_validator('entry_type')
    @classmethod
    def validate_entry_type(cls, v):
        if v not in ['debit', 'credit']:
            raise ValueError('entry_type must be "debit" or "credit"')
        return v


class LedgerEntryResponse(BaseModel):
    """Response model for ledger entries"""
    id: str
    tenant_id: str
    vendor_id: Optional[str] = None
    account: str
    entry_type: str
    amount_minor: int
    currency: str
    cost_centre_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class AccountBalanceResponse(BaseModel):
    """Response model for account balances"""
    account: str
    currency: str
    balance_minor: int
    last_updated: datetime


class LedgerAdjustmentRequest(BaseModel):
    """Request model for ledger adjustments"""
    entry_id: str = Field(..., description="Entry ID to adjust")
    adjustment_amount_minor: int = Field(..., description="Adjustment amount in minor units")
    reason: str = Field(..., description="Reason for adjustment")
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")


class LedgerReportRequest(BaseModel):
    """Request model for ledger reports"""
    tenant_id: str = Field(..., description="Tenant ID")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    account: Optional[str] = None
    cost_centre_id: Optional[str] = None
    currency: Optional[str] = None


# Instant Budget Schemas
class InstantBudgetRequestCreate(BaseModel):
    """Request model for creating instant budget requests"""
    cost_centre_id: str = Field(..., description="Cost centre ID")
    amount_minor: int = Field(..., description="Amount requested in minor units", gt=0)
    reason: Optional[str] = Field(None, description="Reason for the request")
    store_id: Optional[str] = Field(None, description="Store ID (optional)")


class InstantBudgetApproveRequest(BaseModel):
    """Request model for approving instant budget requests"""
    approve: bool = Field(..., description="Whether to approve (true) or reject (false)")
    partial_amount_minor: Optional[int] = Field(None, description="Partial approval amount in minor units (optional)")


class InstantBudgetResponse(BaseModel):
    """Response model for instant budget requests"""
    request_id: str
    status: str
    expires_at: str
    approved_amount_minor: int
    remaining_amount_minor: int
    message: str


class ApproverLimitRequest(BaseModel):
    """Request model for creating/updating approver limits"""
    user_id: str = Field(..., description="User ID of the approver")
    cost_centre_id: Optional[str] = Field(None, description="Cost centre ID (optional, null for global limit)")
    daily_limit_minor: int = Field(..., description="Daily approval limit in minor units", ge=0)
    monthly_limit_minor: int = Field(..., description="Monthly approval limit in minor units", ge=0)
    currency_code: str = Field(default="INR", description="Currency code")

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
    new_password:str = Field(..., min_length=8)

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
    price_id: str | None = None
    amount: int = None
    currency: str = "usd"
    mode: str = "payment"
    billing_cycle: str = "monthly"
    plan_code: str

class BudgetRequestCreate(BaseModel):
    tenant_id: int
    cost_center_id: int
    requested_by: int
    amount: float
    description: str | None = None


class BudgetApprovalCreate(BaseModel):
    budget_request_id: int
    approver_id: int
    approved_amount: float
    comments: str | None = None


class BudgetRequestOut(BaseModel):
    id: int
    tenant_id: int
    cost_center_id: int
    requested_by: int
    amount: float
    status: str
    description: str | None

    class Config:
        orm_mode = True
