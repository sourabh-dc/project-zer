from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime

from supply_v2.models import Vendor
from supply_v2.services.dispute_service import DisputeService
from supply_v2.services.fulfilment_service import FulfilmentService
from supply_v2.services.invoice_service import InvoiceService
from supply_v2.services.notification_service import NotificationService
from supply_v2.services.order_service import OrderService
from supply_v2.services.procurement_service import ProcurementService
from supply_v2.services.sla_service import SLAService
from supply_v2.store import InMemoryStore


@dataclass
class _IdGen:
    counters: dict[str, int]

    def __call__(self, prefix: str) -> str:
        next_value = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = next_value
        return f"{prefix}_{next_value:06d}"


class SupplyPlatform:
    def __init__(self) -> None:
        self.store = InMemoryStore()
        self.id_gen = _IdGen(counters={})
        self.notifications = NotificationService(self.store, self.id_gen)
        self.orders = OrderService(self.store, self.id_gen)
        self.disputes = DisputeService(self.store, self.id_gen)
        self.procurement = ProcurementService(self.store, self.id_gen, self.notifications)
        self.fulfilment = FulfilmentService(self.store, self.id_gen)
        self.invoices = InvoiceService(self.store, self.id_gen)
        self.slas = SLAService(self.store, self.id_gen)

    def register_vendor(
        self,
        tenant_id: str,
        vendor_id: str,
        name: str,
        primary_email: str,
        channel: str = "email_link",
    ) -> Vendor:
        vendor = Vendor(
            vendor_id=vendor_id,
            tenant_id=tenant_id,
            name=name,
            primary_email=primary_email,
            channel=channel,
        )
        self.store.vendors[vendor.vendor_id] = vendor
        self.store.emit("vendor.registered", vendor.vendor_id)
        return vendor

    def place_customer_order(self, tenant_id: str, customer_id: str, ship_to: dict, items: list[dict]):
        order = self.orders.place_order(tenant_id=tenant_id, customer_id=customer_id, ship_to=ship_to, items=items)
        pos = self.procurement.allocate_order(order.order_id)
        for po in pos:
            vendor = self.store.vendors[po.vendor_id]
            self.slas.create_vendor_ack_sla(tenant_id=tenant_id, po_id=po.po_id, hours=vendor.ack_sla_hours)
        self.orders.refresh_order_status(order.order_id)
        return order

    def vendor_acknowledge(self, po_id: str, decisions: list[dict]):
        po = self.procurement.acknowledge_po(po_id=po_id, decisions=decisions, dispute_service=self.disputes)
        self.orders.refresh_order_status(po.order_id)
        return po

    def resolve_vendor_dispute(self, dispute_id: str, resolution: str = "accepted_vendor_terms"):
        if resolution == "accepted_vendor_terms":
            dispute = self.disputes.resolve_accept_vendor_terms(dispute_id)
        else:
            dispute = self.disputes.resolve_reject_vendor_terms(dispute_id)
        order_id = self.store.disputes[dispute_id].order_id
        self.orders.refresh_order_status(order_id)
        return dispute

    def vendor_create_shipment(self, po_id: str, tracking_number: str, lines: list[dict]):
        shipment = self.fulfilment.create_shipment(po_id=po_id, tracking_number=tracking_number, lines=lines)
        self.orders.refresh_order_status(shipment.order_id)
        return shipment

    def customer_record_receipt(self, order_id: str, shipment_id: str, lines: list[dict]):
        receipt = self.fulfilment.record_receipt(
            order_id=order_id,
            shipment_id=shipment_id,
            lines=lines,
            dispute_service=self.disputes,
        )
        self.orders.refresh_order_status(order_id)
        return receipt

    def resolve_customer_dispute(self, dispute_id: str, resolution: str):
        dispute = self.disputes.resolve_customer_shortage(dispute_id, resolution)
        order_id = self.store.disputes[dispute_id].order_id
        self.orders.refresh_order_status(order_id)
        return dispute

    def finalize_order(self, order_id: str) -> None:
        order = self.store.orders[order_id]
        for line_id in order.line_ids:
            line = self.store.order_lines[line_id]
            if line.status in {"received", "procured", "shipped", "cancelled"}:
                line.status = "completed"
        self.orders.refresh_order_status(order_id)

    def create_invoice(self, tenant_id: str, po_id: str, invoice_number: str, lines: list[dict]):
        return self.invoices.create_invoice(
            tenant_id=tenant_id,
            po_id=po_id,
            invoice_number=invoice_number,
            lines=lines,
        )

    def evaluate_slas(self):
        return self.slas.evaluate_due_records()

    def cancel_order_line(self, order_id: str, order_line_id: str, reason: str):
        line = self.procurement.cancel_order_line(order_id=order_id, order_line_id=order_line_id, reason=reason)
        self.orders.refresh_order_status(order_id)
        return line

    def reallocate_order_line(self, order_id: str, order_line_id: str, new_vendor_id: str, reason: str):
        po = self.procurement.reallocate_order_line(
            order_id=order_id,
            order_line_id=order_line_id,
            new_vendor_id=new_vendor_id,
            reason=reason,
        )
        vendor = self.store.vendors[po.vendor_id]
        self.slas.create_vendor_ack_sla(
            tenant_id=self.store.orders[order_id].tenant_id,
            po_id=po.po_id,
            hours=vendor.ack_sla_hours,
        )
        self.orders.refresh_order_status(order_id)
        return po

    def to_snapshot(self) -> dict:
        def encode(value):
            if isinstance(value, datetime):
                return {"__datetime__": value.isoformat()}
            if isinstance(value, dict):
                return {k: encode(v) for k, v in value.items()}
            if isinstance(value, list):
                return [encode(v) for v in value]
            return value

        return {
            "id_counters": dict(self.id_gen.counters),
            "vendors": {key: encode(asdict(value)) for key, value in self.store.vendors.items()},
            "orders": {key: encode(asdict(value)) for key, value in self.store.orders.items()},
            "order_lines": {key: encode(asdict(value)) for key, value in self.store.order_lines.items()},
            "allocations": {key: encode(asdict(value)) for key, value in self.store.allocations.items()},
            "purchase_orders": {key: encode(asdict(value)) for key, value in self.store.purchase_orders.items()},
            "po_lines": {key: encode(asdict(value)) for key, value in self.store.po_lines.items()},
            "notifications": {key: encode(asdict(value)) for key, value in self.store.notifications.items()},
            "disputes": {key: encode(asdict(value)) for key, value in self.store.disputes.items()},
            "shipments": {key: encode(asdict(value)) for key, value in self.store.shipments.items()},
            "shipment_lines": {key: encode(asdict(value)) for key, value in self.store.shipment_lines.items()},
            "receipts": {key: encode(asdict(value)) for key, value in self.store.receipts.items()},
            "receipt_lines": {key: encode(asdict(value)) for key, value in self.store.receipt_lines.items()},
            "invoices": {key: encode(asdict(value)) for key, value in self.store.invoices.items()},
            "invoice_lines": {key: encode(asdict(value)) for key, value in self.store.invoice_lines.items()},
            "sla_records": {key: encode(asdict(value)) for key, value in self.store.sla_records.items()},
            "events": encode(list(self.store.events)),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "SupplyPlatform":
        platform = cls()
        platform.id_gen.counters = dict(snapshot.get("id_counters", {}))

        def decode(value):
            if isinstance(value, dict) and "__datetime__" in value:
                return datetime.fromisoformat(value["__datetime__"])
            if isinstance(value, dict):
                return {k: decode(v) for k, v in value.items()}
            if isinstance(value, list):
                return [decode(v) for v in value]
            return value

        def restore(model_cls, name: str) -> dict:
            return {
                key: model_cls(**decode(value))
                for key, value in snapshot.get(name, {}).items()
            }

        from supply_v2.models import (
            CustomerOrder,
            CustomerOrderLine,
            Dispute,
            GoodsReceipt,
            GoodsReceiptLine,
            Invoice,
            InvoiceLine,
            Notification,
            PurchaseOrder,
            PurchaseOrderLine,
            SLARecord,
            Shipment,
            ShipmentLine,
            VendorAllocation,
        )

        platform.store.vendors = restore(Vendor, "vendors")
        platform.store.orders = restore(CustomerOrder, "orders")
        platform.store.order_lines = restore(CustomerOrderLine, "order_lines")
        platform.store.allocations = restore(VendorAllocation, "allocations")
        platform.store.purchase_orders = restore(PurchaseOrder, "purchase_orders")
        platform.store.po_lines = restore(PurchaseOrderLine, "po_lines")
        platform.store.notifications = restore(Notification, "notifications")
        platform.store.disputes = restore(Dispute, "disputes")
        platform.store.shipments = restore(Shipment, "shipments")
        platform.store.shipment_lines = restore(ShipmentLine, "shipment_lines")
        platform.store.receipts = restore(GoodsReceipt, "receipts")
        platform.store.receipt_lines = restore(GoodsReceiptLine, "receipt_lines")
        platform.store.invoices = restore(Invoice, "invoices")
        platform.store.invoice_lines = restore(InvoiceLine, "invoice_lines")
        platform.store.sla_records = restore(SLARecord, "sla_records")
        platform.store.events = decode(list(snapshot.get("events", [])))
        return platform
