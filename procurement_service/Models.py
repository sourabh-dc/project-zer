from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Vendor:
    vendor_id: str
    tenant_id: str
    name: str
    primary_email: str
    channel: str = "email_link"
    ack_sla_hours: int = 24
    shipment_sla_hours: int = 72
    active: bool = True
    # Integration protocol: api | cxml | edi | email
    preferred_protocol: str = "email"
    api_endpoint_url: Optional[str] = None
    cxml_endpoint_url: Optional[str] = None
    edi_partner_id: Optional[str] = None
    notification_email: Optional[str] = None
    webhook_url: Optional[str] = None
    onboarding_status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class CustomerOrder:
    order_id: str
    tenant_id: str
    order_number: str
    customer_id: str
    ship_to: dict[str, Any]
    status: str = "placed"
    line_ids: list[str] = field(default_factory=list)
    po_ids: list[str] = field(default_factory=list)
    receipt_ids: list[str] = field(default_factory=list)
    dispute_ids: list[str] = field(default_factory=list)
    event_log: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class CustomerOrderLine:
    order_line_id: str
    tenant_id: str
    order_id: str
    vendor_id: str
    sku: str
    description: str
    ordered_quantity: int
    unit_price_minor: int
    status: str = "placed"
    allocated_quantity: int = 0
    shipped_quantity: int = 0
    received_quantity: int = 0
    disputed_quantity: int = 0
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class VendorAllocation:
    allocation_id: str
    tenant_id: str
    order_id: str
    order_line_id: str
    vendor_id: str
    quantity: int
    reason: str = "initial_allocation"
    status: str = "allocated"
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class PurchaseOrder:
    po_id: str
    tenant_id: str
    po_number: str
    order_id: str
    vendor_id: str
    ship_to: dict[str, Any]
    status: str = "issued"
    version: int = 1
    line_ids: list[str] = field(default_factory=list)
    dispute_ids: list[str] = field(default_factory=list)
    event_log: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class PurchaseOrderLine:
    po_line_id: str
    tenant_id: str
    po_id: str
    order_line_id: str
    vendor_id: str
    sku: str
    description: str
    ordered_quantity: int
    unit_price_minor: int
    accepted_quantity: Optional[int] = None
    accepted_unit_price_minor: Optional[int] = None
    shipped_quantity: int = 0
    received_quantity: int = 0
    status: str = "issued"
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Notification:
    notification_id: str
    tenant_id: str
    target_email: str
    template: str
    vendor_id: Optional[str] = None
    po_id: Optional[str] = None
    status: str = "queued"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Dispute:
    dispute_id: str
    dispute_type: str
    source: str
    tenant_id: str
    order_id: str
    status: str = "submitted"
    vendor_id: Optional[str] = None
    po_id: Optional[str] = None
    po_line_id: Optional[str] = None
    order_line_id: Optional[str] = None
    requested_quantity: Optional[int] = None
    proposed_quantity: Optional[int] = None
    proposed_unit_price_minor: Optional[int] = None
    claimed_quantity: Optional[int] = None
    reason: str = ""
    resolution: Optional[str] = None
    history: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Shipment:
    shipment_id: str
    tenant_id: str
    po_id: str
    order_id: str
    vendor_id: str
    tracking_number: str
    status: str = "in_transit"
    line_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ShipmentLine:
    shipment_line_id: str
    tenant_id: str
    shipment_id: str
    po_line_id: str
    order_line_id: str
    quantity: int
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class GoodsReceipt:
    receipt_id: str
    tenant_id: str
    order_id: str
    shipment_id: str
    status: str = "recorded"
    line_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class GoodsReceiptLine:
    receipt_line_id: str
    tenant_id: str
    receipt_id: str
    shipment_line_id: str
    order_line_id: str
    expected_quantity: int
    received_quantity: int
    condition: str = "good"
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Invoice:
    invoice_id: str
    tenant_id: str
    po_id: str
    invoice_number: str
    status: str = "received"
    line_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class InvoiceLine:
    invoice_line_id: str
    tenant_id: str
    invoice_id: str
    po_line_id: str
    billed_quantity: int
    billed_unit_price_minor: int
    match_status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class SLARecord:
    sla_id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    metric: str
    due_at: datetime
    status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class IdempotencyRecord:
    key_id: str
    tenant_id: str
    idempotency_key: str
    endpoint: str
    response_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class BrokerMessage:
    message_id: str
    topic: str
    payload: dict[str, Any]
    status: str = "queued"
    attempts: int = 0
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class DeadLetter:
    dead_letter_id: str
    message_id: str
    topic: str
    payload: dict[str, Any]
    reason: str
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class EmailDelivery:
    delivery_id: str
    notification_id: str
    provider: str
    status: str
    external_message_id: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
