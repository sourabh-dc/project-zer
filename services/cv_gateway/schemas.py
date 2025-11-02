from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Any, Dict
from datetime import datetime
import uuid
# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

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

    # External IDs (optional if local IDs are provided)
    tenant_ext_id: Optional[str] = Field(None, description="External tenant ID")
    site_ext_id: Optional[str] = Field(None, description="External site ID")
    store_ext_id: Optional[str] = Field(None, description="External store ID")
    user_ext_id: Optional[str] = Field(None, description="External user ID")

    # Local IDs (preferred)
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
    """Phase 2: Update device status"""
    status: str = Field(..., description="Device status: online, offline, error, maintenance")
    health_score: Optional[int] = Field(None, description="Health score 0-100", ge=0, le=100)
    details: Optional[Dict[str, Any]] = Field(None, description="Status details")

class DeviceAlertCreate(BaseModel):
    """Phase 2: Create device alert"""
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
