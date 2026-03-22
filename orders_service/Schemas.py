from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PurchaseRequestCreate(BaseModel):
    cost_centre_id: str
    vendor_id: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = Field(
        None, description="[{product_id, qty, unit_price_minor, description}]"
    )
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="GBP", max_length=3)
    notes: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(description="approve | reject | escalate")
    note: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
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

