from __future__ import annotations

from dataclasses import dataclass, field

from supply_v2.models import (
    CustomerOrder,
    CustomerOrderLine,
    Dispute,
    GoodsReceipt,
    GoodsReceiptLine,
    IdempotencyRecord,
    Invoice,
    InvoiceLine,
    Notification,
    OutboxEvent,
    PurchaseOrder,
    PurchaseOrderLine,
    Shipment,
    ShipmentLine,
    SLARecord,
    Vendor,
    VendorAllocation,
)


@dataclass
class InMemoryStore:
    vendors: dict[str, Vendor] = field(default_factory=dict)
    orders: dict[str, CustomerOrder] = field(default_factory=dict)
    order_lines: dict[str, CustomerOrderLine] = field(default_factory=dict)
    allocations: dict[str, VendorAllocation] = field(default_factory=dict)
    purchase_orders: dict[str, PurchaseOrder] = field(default_factory=dict)
    po_lines: dict[str, PurchaseOrderLine] = field(default_factory=dict)
    notifications: dict[str, Notification] = field(default_factory=dict)
    outbox_events: dict[str, OutboxEvent] = field(default_factory=dict)
    disputes: dict[str, Dispute] = field(default_factory=dict)
    shipments: dict[str, Shipment] = field(default_factory=dict)
    shipment_lines: dict[str, ShipmentLine] = field(default_factory=dict)
    receipts: dict[str, GoodsReceipt] = field(default_factory=dict)
    receipt_lines: dict[str, GoodsReceiptLine] = field(default_factory=dict)
    invoices: dict[str, Invoice] = field(default_factory=dict)
    invoice_lines: dict[str, InvoiceLine] = field(default_factory=dict)
    sla_records: dict[str, SLARecord] = field(default_factory=dict)
    idempotency_records: dict[str, IdempotencyRecord] = field(default_factory=dict)
    events: list[dict[str, str]] = field(default_factory=list)

    def emit(self, event_type: str, entity_id: str) -> None:
        self.events.append({"event_type": event_type, "entity_id": entity_id})
