from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    vendor_id: str
    name: str
    primary_email: str
    channel: str = "email_link"


class OrderItemIn(BaseModel):
    vendor_id: str
    sku: str
    description: str
    quantity: int = Field(ge=1)
    unit_price_minor: int = Field(ge=0)


class OrderCreate(BaseModel):
    customer_id: str
    customer_email: str
    ship_to: dict[str, Any]
    items: list[OrderItemIn]


class AckDecisionIn(BaseModel):
    po_line_id: str
    accepted_quantity: int = Field(ge=0)
    proposed_unit_price_minor: Optional[int] = Field(default=None, ge=0)
    status: str
    reason: str = ""


class ShipmentLineIn(BaseModel):
    po_line_id: str
    quantity: int = Field(ge=1)


class ShipmentCreate(BaseModel):
    tracking_number: str
    lines: list[ShipmentLineIn]


class ReceiptLineIn(BaseModel):
    shipment_line_id: str
    received_quantity: int = Field(ge=0)
    condition: str = "good"


class ReceiptCreate(BaseModel):
    shipment_id: str
    lines: list[ReceiptLineIn]


class DisputeResolveIn(BaseModel):
    resolution: str


class CustomerDisputeRaiseIn(BaseModel):
    order_line_id: str
    claimed_quantity: int = Field(ge=0)
    reason: str


class VendorDisputeRaiseIn(BaseModel):
    po_line_id: str
    status: str
    accepted_quantity: int = Field(ge=0)
    proposed_unit_price_minor: Optional[int] = Field(default=None, ge=0)
    reason: str


class InvoiceLineIn(BaseModel):
    po_line_id: str
    billed_quantity: int = Field(ge=0)
    billed_unit_price_minor: int = Field(ge=0)


class InvoiceCreate(BaseModel):
    invoice_number: str
    lines: list[InvoiceLineIn]


class CancelLineIn(BaseModel):
    order_line_id: str
    reason: str


class ReallocateLineIn(BaseModel):
    order_line_id: str
    new_vendor_id: str
    reason: str


# =============================================================================
# VENDOR INTEGRATION SCHEMAS
# =============================================================================

class VendorIntegrationConfig(BaseModel):
    """Configure a vendor's integration endpoint and protocol."""
    preferred_protocol: str = Field(
        default="email",
        description="Communication protocol: api | cxml | edi | email",
    )
    # API integration
    api_endpoint_url: Optional[str] = None
    api_auth_type: Optional[str] = Field(
        default=None, description="Auth type: bearer | basic | api_key | oauth2 | hmac"
    )
    api_auth_header: Optional[str] = None
    api_auth_token: Optional[str] = None
    # cXML integration
    cxml_endpoint_url: Optional[str] = None
    cxml_from_identity: Optional[str] = None
    cxml_to_identity: Optional[str] = None
    cxml_shared_secret: Optional[str] = None
    # EDI integration
    edi_partner_id: Optional[str] = None
    edi_interchange_qualifier: Optional[str] = None
    edi_protocol: Optional[str] = Field(
        default=None, description="Transport: as2 | sftp | van"
    )
    edi_connection_config: Optional[dict[str, Any]] = None
    # Notifications
    notification_email: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None


class VendorOnboardingUpdate(BaseModel):
    """Update vendor onboarding metadata."""
    onboarding_status: Optional[str] = None
    payment_terms: Optional[str] = None
    return_policy: Optional[str] = None
    lead_time_days: Optional[int] = Field(default=None, ge=0)
    minimum_order_minor: Optional[int] = Field(default=None, ge=0)
    tax_id: Optional[str] = None
    duns_number: Optional[str] = None
    vendor_metadata: Optional[dict[str, Any]] = None


class VendorFulfillmentUpdate(BaseModel):
    """Vendor-facing update on an order / PO status."""
    status: str = Field(description="acknowledged | shipped | partially_shipped | cancelled")
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[str] = None
    lines: Optional[list[ShipmentLineIn]] = None
    note: Optional[str] = None


class OrderDispatchPayload(BaseModel):
    """Internal representation of an order dispatched to a vendor via any protocol."""
    po_id: str
    po_number: str
    vendor_id: str
    tenant_id: str
    ship_to: dict[str, Any]
    lines: list[dict[str, Any]]
    currency: str = "GBP"
    note: Optional[str] = None
