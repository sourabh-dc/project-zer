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
