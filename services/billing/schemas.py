import uuid
from datetime import date, datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# PAYLOADS (Pydantic)
# =============================================================================

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

        # Check for duplicate line numbers
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


# Phase 4: Cost Centre Budgeting Models
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
    budget_type: str = Field(..., description="Budget type", regex="^(annual|monthly|project)$")
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