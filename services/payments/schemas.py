# =============================================================================
# PYDANTIC MODELS
# =============================================================================
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


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
    amount_minor: Optional[int] = Field(None, description="Refund amount in minor units (full if not specified)")
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

class RailRequest(BaseModel):
    """Request model for payment provider configuration"""
    tenant_id: str = Field(..., description="Tenant ID")
    type: str = Field(default="payment", description="Rail type")
    name: str = Field(..., description="Provider name (e.g., stripe, adyen)")
    config: Dict[str, Any] = Field(..., description="Provider configuration")

# Phase 5: Trade Account & Multi-Currency Models
class TradeAccountRequest(BaseModel):
    """Trade account creation request - Phase 5"""
    company_name: str = Field(..., description="Company name", max_length=200)
    contact_email: str = Field(..., description="Contact email", max_length=255)
    credit_limit_minor: int = Field(..., description="Credit limit in minor units", ge=0)
    currency: str = Field("GBP", description="Currency code", max_length=3)
    payment_terms_days: int = Field(30, description="Payment terms in days", ge=0)

class TradeAccountResponse(BaseModel):
    """Trade account response model - Phase 5"""
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

class PaymentIntentRequest(BaseModel):
    """Payment intent creation request - Phase 5"""
    order_id: Optional[str] = Field(None, description="Associated order ID")
    trade_account_id: Optional[str] = Field(None, description="Trade account ID")
    amount_minor: int = Field(..., description="Amount in minor units", gt=0)
    currency: str = Field("GBP", description="Currency code", max_length=3)
    payment_method: str = Field("card", description="Payment method", pattern="^(card|bank_transfer|wallet)$")
    description: Optional[str] = Field(None, description="Payment description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class PaymentIntentResponse(BaseModel):
    """Payment intent response model - Phase 5"""
    payment_intent_id: str
    client_secret: str
    amount_minor: int
    currency: str
    status: str
    provider: str
    expires_at: Optional[datetime]

class MultiCurrencyConversionRequest(BaseModel):
    """Currency conversion request - Phase 5"""
    from_currency: str = Field(..., description="Source currency", max_length=3)
    to_currency: str = Field(..., description="Target currency", max_length=3)
    amount_minor: int = Field(..., description="Amount in minor units", gt=0)

class MultiCurrencyConversionResponse(BaseModel):
    """Currency conversion response - Phase 5"""
    from_currency: str
    to_currency: str
    original_amount_minor: int
    converted_amount_minor: int
    exchange_rate: float
    converted_at: datetime