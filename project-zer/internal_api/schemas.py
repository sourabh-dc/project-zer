from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class PlanCreateRequest(BaseModel):
    plan_id: Optional[int] = Field(default=None, description="Optional explicit plan id")
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    meta: Optional[Dict[str, Any]] = Field(default=None, description="Optional plan metadata")
    created_by: Optional[str] = Field(default="zeroque_admin", max_length=100)


class PlanPriceRequest(BaseModel):
    plan_code: str
    price_monthly_minor: int = Field(ge=0)
    currency: str = Field(default="GBP", max_length=3)
    quarterly_discount_pct: float = Field(default=5.0, ge=0, le=100)
    yearly_discount_pct: float = Field(default=10.0, ge=0, le=100)


class FeatureCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    cluster: Optional[str] = Field(None, max_length=50)
    usage_type: Optional[str] = Field(default="count", max_length=50)
    max_unit: Optional[str] = Field(default=None, max_length=50)
    reset_period: Optional[str] = Field(default="monthly", max_length=20)


class PlanFeatureMapRequest(BaseModel):
    plan_code: str
    feature_code: str
    limits: Optional[Dict[str, Any]] = None


class RoleCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class PermissionCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=500)

