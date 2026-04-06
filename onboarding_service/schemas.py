"""
onboarding_service.schemas
---------------------------
Pydantic request/response models for tenant onboarding.
Authentication (password, OTP, email verification) is handled by Auth0.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TenantSignupRequest(BaseModel):
    """Tenant creation — company signup with admin details.
    No password: Auth0 handles authentication, OTP, and password management.
    """
    tenant_name: str = Field(..., min_length=2, max_length=200)
    type: str = Field(..., description="customer | retailer | distributor")
    email: str = Field(..., min_length=5, description="Tenant contact email")
    admin_email: str = Field(..., min_length=5, description="Admin user email")
    admin_firstname: str = Field(..., min_length=1, max_length=150)
    admin_lastname: str = Field(..., min_length=1, max_length=150)

    registration_number: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = None
    billing_email: Optional[str] = None
    default_currency: Optional[str] = Field("GBP", max_length=3)
    timezone: Optional[str] = Field("UTC")
    locale: Optional[str] = Field("en_GB")
    industry: Optional[str] = None
    primary_domain: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        allowed = ("customer", "retailer", "distributor")
        if v not in allowed:
            raise ValueError(f"type must be one of: {', '.join(allowed)}")
        return v
