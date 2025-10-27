# Request Models
from datetime import datetime
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class CreatePlanRequest(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    price_yearly_minor: int
    currency: str = "GBP"

class CreateSubscriptionRequest(BaseModel):
    tenant_id: str
    plan_code: str
    billing_cycle: str = "yearly"
    auto_renew: bool = True

class TenantSubscriptionPayload(BaseModel):
    plan_code: str = Field(..., description="Subscription plan code")
    payment_method: str = Field(..., description="Payment method: stripe, trade")
    external_id: Optional[str] = Field(None, description="External subscription ID")
    current_period_start: Optional[datetime] = Field(None)
    current_period_end: Optional[datetime] = Field(None)
    trial_end: Optional[datetime] = Field(None)

class CreateBillingAccountPayload(BaseModel):
    site_id: str = Field(..., description="Site ID")
    payment_method: str = Field(..., description="Payment method: stripe, trade")
    external_id: str = Field(..., description="External billing account ID")
    metadata: Optional[Dict[str, Any]] = Field(None)