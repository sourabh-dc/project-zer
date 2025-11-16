import uuid
from datetime import datetime, date
from pydantic import field_validator, BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, Dict, List, Tuple, Any
import re

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
    tenant_id: str = Field(description="Tenant ID")
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
    currency: str = Field(default="GBP", max_length=3, description="Currency code")


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
    requested_by: str = Field(description="Requester user ID")
    total_amount_minor: Optional[int] = Field(None, ge=0, description="Amount in minor units (optional)")
    currency: str = Field(default="GBP", max_length=3, description="Currency code")
    due_date: Optional[datetime] = Field(None, description="Due date (optional)")


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


class CostCentreRequest(BaseModel):
    """Cost centre creation request - Phase 4"""
    name: str = Field(..., description="Cost centre name", max_length=200)
    code: str = Field(..., description="Cost centre code (e.g., IT-001)", max_length=50)
    description: Optional[str] = Field(None, description="Cost centre description")
    parent_cost_centre_id: Optional[str] = Field(None, description="Parent cost centre ID for hierarchy")
    budget_owner_id: str = Field(..., description="User ID who owns the budget")


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

class ProviderConfig(BaseModel):
    """Provider configuration schema"""
    provider: str = Field(..., description="Provider name (aifi, etc.)")
    api_key: str = Field(..., description="API key")
    base_url: str = Field(..., description="Base URL")
    location_id: Optional[str] = Field(None, description="Location ID if required")
    store_id: Optional[str] = Field(None, description="Store ID if required")


class ZeroqueRailRequest(BaseModel):
    """Request to create/update zeroque rail"""
    type: str = Field("cv", description="Rail type")
    name: str = Field(..., description="Provider name")
    config: ProviderConfig = Field(..., description="Provider configuration")
    active: bool = Field(True, description="Whether rail is active")


class ProviderParam(BaseModel):
    """Provider parameter for multi-provider support"""
    provider: str = Field(..., description="Provider name")


class EntryCodeCreate(BaseModel):
    """Create entry code request"""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    provider: Optional[str] = Field(None, description="Provider override")
    group_size: Optional[int] = Field(None, description="Group size")
    displayable: bool = Field(True, description="Generate QR code")
    extra: Optional[Dict[str, Any]] = Field(None, description="Additional data")

    @field_validator('tenant_id', 'user_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')


class EntryVerifyRequest(BaseModel):
    """Verify entry code request"""
    tenant_id: str = Field(..., description="Tenant ID")
    verification_code: str = Field(..., description="Verification code")
    store_id: str = Field(..., description="Store ID")
    entry_id: str = Field(..., description="Entry ID")
    provider: Optional[str] = Field(None, description="Provider override")
    group_size: Optional[int] = Field(None, description="Group size")
    check_in_device_id: Optional[int] = Field(None, description="Check-in device ID")

    @field_validator('tenant_id', 'store_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')


class EntryVerifyResponse(BaseModel):
    """Entry verification response"""
    status: str = Field(..., description="Verification status")
    session_id: Optional[str] = Field(None, description="Session ID")
    reason: Optional[str] = Field(None, description="Failure reason")
    shopper_role: Optional[str] = Field(None, description="Shopper role")


class EntryWebhookDecision(BaseModel):
    """Entry webhook decision"""
    status: str = Field(..., description="Decision status")
    reason: Optional[str] = Field(None, description="Decision reason")


class CardEntryRequest(BaseModel):
    """Card-based entry request"""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    store_id: str = Field(..., description="Store ID")
    card_number: str = Field(..., description="Card number (last 4 digits or full encrypted)")
    card_type: str = Field("rfid", description="Card type: 'rfid', 'nfc', 'magnetic'")
    device_id: Optional[str] = Field(None, description="Entry device ID")
    provider: Optional[str] = Field(None, description="Provider override")

    @field_validator('tenant_id', 'user_id', 'store_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')


class BiometricEntryRequest(BaseModel):
    """Biometric-based entry request"""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    store_id: str = Field(..., description="Store ID")
    biometric_type: str = Field(..., description="Biometric type: 'fingerprint', 'face', 'palm', 'iris'")
    biometric_data: str = Field(..., description="Base64-encoded biometric template/hash")
    device_id: Optional[str] = Field(None, description="Entry device ID")
    confidence_score: Optional[float] = Field(None, description="Biometric match confidence (0-1)")
    provider: Optional[str] = Field(None, description="Provider override")

    @field_validator('tenant_id', 'user_id', 'store_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')


class SimpleOK(BaseModel):
    """Simple OK response"""
    ok: bool = Field(..., description="Success status")


class CustomerUpsert(BaseModel):
    """Customer upsert schema"""
    external_id: str = Field(..., description="External customer ID")
    email: Optional[str] = Field(None, description="Customer email")
    first_name: Optional[str] = Field(None, description="First name")
    last_name: Optional[str] = Field(None, description="Last name")
    phone: Optional[str] = Field(None, description="Phone number")
    role: str = Field("customer", description="Customer role")
    password: Optional[str] = Field(None, description="Password")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class ProductUpsert(BaseModel):
    """Product upsert schema"""
    external_id: str = Field(..., description="External product ID")
    name: str = Field(..., description="Product name")
    price: Optional[float] = Field(None, description="Product price")
    barcode: Optional[str] = Field(None, description="Product barcode")
    restricted: bool = Field(False, description="Restricted item")
    tax_code: Optional[str] = Field(None, description="Tax code")
    variants: List[dict] = Field(default_factory=list, description="Product variants")


class InventoryAdjust(BaseModel):
    """Inventory adjustment schema"""
    product_id: str = Field(..., description="Product ID")
    quantity_difference: Optional[int] = Field(None, description="Quantity difference")
    quantity: Optional[int] = Field(None, description="Absolute quantity")


class SyncBatchRequest(BaseModel):
    """Batch sync request"""
    tenant_id: str = Field(..., description="Tenant ID")
    provider: Optional[str] = Field(None, description="Provider override")
    customers: List[CustomerUpsert] = Field(default_factory=list, description="Customers to sync")
    products: List[ProductUpsert] = Field(default_factory=list, description="Products to sync")
    inventory: List[InventoryAdjust] = Field(default_factory=list, description="Inventory adjustments")

    @field_validator('tenant_id')
    @classmethod
    def validate_tenant_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid tenant_id format')

class AiFiItem(BaseModel):
    """CV order item"""
    sku: str = Field(..., description="Product SKU")
    name: str = Field(..., description="Product name")
    qty: int = Field(..., description="Quantity")
    price_minor: int = Field(..., description="Price in minor units")


class AiFiOrder(BaseModel):
    """CV order from provider"""
    provider: str = Field(..., description="Provider name")
    provider_order_id: str = Field(..., description="Provider order ID")
    tenant_ext_id: Optional[str] = Field(None, description="External tenant ID")
    site_ext_id: Optional[str] = Field(None, description="External site ID")
    store_ext_id: Optional[str] = Field(None, description="External store ID")
    user_ext_id: Optional[str] = Field(None, description="External user ID")
    tenant_id: Optional[str] = Field(None, description="Local tenant ID")
    site_id: Optional[str] = Field(None, description="Local site ID")
    store_id: Optional[str] = Field(None, description="Local store ID")
    shopper_id: Optional[str] = Field(None, description="Local shopper ID")
    currency: str = Field("GBP", description="Currency")
    items: List[AiFiItem] = Field(..., description="Order items")
    occurred_at: Optional[datetime] = Field(None, description="Order timestamp")

    @field_validator('tenant_id', 'site_id', 'store_id', 'shopper_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError('Invalid UUID format')
        return v


class DeviceStatusUpdate(BaseModel):
    """Update device status"""
    status: str = Field(..., description="Device status: online, offline, error, maintenance")
    health_score: Optional[int] = Field(None, description="Health score 0-100", ge=0, le=100)
    details: Optional[Dict[str, Any]] = Field(None, description="Status details")


class DeviceAlertCreate(BaseModel):
    """Create device alert"""
    alert_type: str = Field(..., description="Alert type: offline, error, low_health")
    severity: str = Field("warning", description="Severity: info, warning, critical")
    message: str = Field(..., description="Alert message")


class ReviewResolvePayload(BaseModel):
    """Review resolution payload"""
    mapped_sku: Optional[str] = Field(None, description="Mapped SKU")
    status: str = Field("resolved", description="Resolution status")
    notes: Optional[str] = Field(None, description="Resolution notes")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in ("resolved", "ignored"):
            raise ValueError("Status must be 'resolved' or 'ignored'")
        return v


class OrderResponse(BaseModel):
    """Order processing response"""
    ok: bool = Field(..., description="Success status")
    order_id: Optional[int] = Field(None, description="Created order ID")
    total_minor: Optional[int] = Field(None, description="Total amount in minor units")
    currency: Optional[str] = Field(None, description="Currency")
    unknown_items: Optional[List[dict]] = Field(None, description="Unknown items requiring review")