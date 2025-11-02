from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from datetime import datetime
# =============================================================================
# PYDANTIC MODELS
# =============================================================================

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
    idempotency_key: Optional[str] = Field(None, description="Idempotency key to prevent duplicate entries")

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
    idempotency_key: Optional[str] = Field(None, description="Idempotency key to prevent duplicate adjustments")

class LedgerReportRequest(BaseModel):
    """Request model for ledger reports"""
    tenant_id: str = Field(..., description="Tenant ID")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    account: Optional[str] = None
    cost_centre_id: Optional[str] = None
    currency: Optional[str] = None