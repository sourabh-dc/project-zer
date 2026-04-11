from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from procurement_service.Models import (
    BrokerMessage,
    CustomerOrder,
    CustomerOrderLine,
    DeadLetter,
    Dispute,
    EmailDelivery,
    GoodsReceipt,
    GoodsReceiptLine,
    IdempotencyRecord,
    Invoice,
    InvoiceLine,
    Notification,
    PurchaseOrder,
    PurchaseOrderLine,
    Shipment,
    ShipmentLine,
    SLARecord,
    Vendor,
    VendorAllocation,
    utc_now,
)
from procurement_service.core.config import SETTINGS


def issue_vendor_token(*, tenant_id: str, vendor_id: str, po_id: str, ttl_seconds: int = 86400) -> str:
    payload = {
        "tenant_id": tenant_id,
        "vendor_id": vendor_id,
        "po_id": po_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(
        os.environ.get("SUPPLY_V2_VENDOR_LINK_SECRET", "local-vendor-link-secret").encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{body}.{signature}"


def verify_vendor_token(token: str) -> dict:
    body, signature = token.split(".", 1)
    expected = hmac.new(
        os.environ.get("SUPPLY_V2_VENDOR_LINK_SECRET", "local-vendor-link-secret").encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid vendor token")
    payload = json.loads(base64.urlsafe_b64decode((body + "=" * (-len(body) % 4)).encode("utf-8")).decode("utf-8"))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("vendor token expired")
    return payload


@dataclass
class InMemoryStore:
    vendors: dict[str, Vendor] = field(default_factory=dict)
    orders: dict[str, CustomerOrder] = field(default_factory=dict)
    order_lines: dict[str, CustomerOrderLine] = field(default_factory=dict)
    allocations: dict[str, VendorAllocation] = field(default_factory=dict)
    purchase_orders: dict[str, PurchaseOrder] = field(default_factory=dict)
    po_lines: dict[str, PurchaseOrderLine] = field(default_factory=dict)
    notifications: dict[str, Notification] = field(default_factory=dict)
    disputes: dict[str, Dispute] = field(default_factory=dict)
    shipments: dict[str, Shipment] = field(default_factory=dict)
    shipment_lines: dict[str, ShipmentLine] = field(default_factory=dict)
    receipts: dict[str, GoodsReceipt] = field(default_factory=dict)
    receipt_lines: dict[str, GoodsReceiptLine] = field(default_factory=dict)
    invoices: dict[str, Invoice] = field(default_factory=dict)
    invoice_lines: dict[str, InvoiceLine] = field(default_factory=dict)
    sla_records: dict[str, SLARecord] = field(default_factory=dict)
    idempotency_records: dict[str, IdempotencyRecord] = field(default_factory=dict)
    broker_messages: dict[str, BrokerMessage] = field(default_factory=dict)
    dead_letters: dict[str, DeadLetter] = field(default_factory=dict)
    email_deliveries: dict[str, EmailDelivery] = field(default_factory=dict)
    events: list[dict[str, str]] = field(default_factory=list)

    def emit(self, event_type: str, entity_id: str) -> None:
        self.events.append({"event_type": event_type, "entity_id": entity_id})


@dataclass
class IdGen:
    counters: dict[str, int] = field(default_factory=dict)

    def __call__(self, prefix: str) -> str:
        value = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = value
        return f"{prefix}_{value:06d}"


class ProcurementPlatform:
    def __init__(self) -> None:
        self.store = InMemoryStore()
        self.id_gen = IdGen()

    def register_vendor(self, tenant_id: str, vendor_id: str, name: str, primary_email: str, channel: str = "email_link") -> Vendor:
        vendor = Vendor(vendor_id=vendor_id, tenant_id=tenant_id, name=name, primary_email=primary_email, channel=channel)
        self.store.vendors[vendor.vendor_id] = vendor
        self.store.emit("vendor.registered", vendor.vendor_id)
        return vendor

    def place_customer_order(self, tenant_id: str, customer_id: str, customer_email: str, ship_to: dict, items: list[dict]) -> CustomerOrder:
        order = CustomerOrder(
            order_id=self.id_gen("order"),
            tenant_id=tenant_id,
            order_number=f"ORD-{len(self.store.orders) + 1:06d}",
            customer_id=customer_id,
            ship_to=ship_to,
            status="allocating",
        )
        self.store.orders[order.order_id] = order

        grouped = defaultdict(list)
        for item in items:
            line = CustomerOrderLine(
                order_line_id=self.id_gen("order_line"),
                tenant_id=tenant_id,
                order_id=order.order_id,
                vendor_id=item["vendor_id"],
                sku=item["sku"],
                description=item["description"],
                ordered_quantity=item["quantity"],
                unit_price_minor=item["unit_price_minor"],
                status="allocated",
                allocated_quantity=item["quantity"],
            )
            self.store.order_lines[line.order_line_id] = line
            order.line_ids.append(line.order_line_id)
            grouped[line.vendor_id].append(line)
            allocation = VendorAllocation(
                allocation_id=self.id_gen("allocation"),
                tenant_id=tenant_id,
                order_id=order.order_id,
                order_line_id=line.order_line_id,
                vendor_id=line.vendor_id,
                quantity=line.ordered_quantity,
            )
            self.store.allocations[allocation.allocation_id] = allocation

        for vendor_id, vendor_lines in grouped.items():
            po = PurchaseOrder(
                po_id=self.id_gen("po"),
                tenant_id=tenant_id,
                po_number=f"PO-{len(self.store.purchase_orders) + 1:06d}",
                order_id=order.order_id,
                vendor_id=vendor_id,
                ship_to=ship_to,
            )
            self.store.purchase_orders[po.po_id] = po
            order.po_ids.append(po.po_id)
            for line in vendor_lines:
                po_line = PurchaseOrderLine(
                    po_line_id=self.id_gen("po_line"),
                    tenant_id=tenant_id,
                    po_id=po.po_id,
                    order_line_id=line.order_line_id,
                    vendor_id=vendor_id,
                    sku=line.sku,
                    description=line.description,
                    ordered_quantity=line.ordered_quantity,
                    unit_price_minor=line.unit_price_minor,
                    accepted_unit_price_minor=line.unit_price_minor,
                )
                self.store.po_lines[po_line.po_line_id] = po_line
                po.line_ids.append(po_line.po_line_id)

            vendor = self.store.vendors[vendor_id]
            token = issue_vendor_token(tenant_id=tenant_id, vendor_id=vendor_id, po_id=po.po_id)
            action_base = f"{SETTINGS.APP_BASE_URL.rstrip('/')}/vendor/purchase-orders/{po.po_id}"
            notification = Notification(
                notification_id=self.id_gen("notification"),
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                po_id=po.po_id,
                target_email=vendor.primary_email,
                template="vendor_po_email",
                payload={
                    "po_number": po.po_number,
                    "vendor_token": token,
                    "accept_url": f"{action_base}?action=accept&token={token}",
                    "reject_url": f"{action_base}?action=reject&token={token}",
                    "partial_url": f"{action_base}?action=partial&token={token}",
                },
            )
            self.store.notifications[notification.notification_id] = notification
            sla = SLARecord(
                sla_id=self.id_gen("sla"),
                tenant_id=tenant_id,
                entity_type="purchase_order",
                entity_id=po.po_id,
                metric="vendor_ack_due",
                due_at=utc_now() + timedelta(hours=vendor.ack_sla_hours),
            )
            self.store.sla_records[sla.sla_id] = sla
            self.store.emit("purchase_order.issued", po.po_id)
            self.store.emit("vendor_notification.queued", notification.notification_id)

        order_total_minor = 0
        order_items: list[dict] = []
        for line_id in order.line_ids:
            line = self.store.order_lines[line_id]
            line_total = line.ordered_quantity * line.unit_price_minor
            order_total_minor += line_total
            order_items.append(
                {
                    "sku": line.sku,
                    "description": line.description,
                    "quantity": line.ordered_quantity,
                    "unit_price_minor": line.unit_price_minor,
                    "line_total_minor": line_total,
                }
            )

        if customer_email:
            customer_notification = Notification(
                notification_id=self.id_gen("notification"),
                tenant_id=tenant_id,
                target_email=customer_email,
                template="customer_order_summary",
                payload={
                    "order_id": order.order_id,
                    "order_number": order.order_number,
                    "order_total_minor": order_total_minor,
                    "currency": "USD",
                    "items": order_items,
                },
            )
            self.store.notifications[customer_notification.notification_id] = customer_notification
            self.store.emit("customer_notification.queued", customer_notification.notification_id)

        self.store.emit("customer_order.placed", order.order_id)
        self.store.emit("customer_order.procured", order.order_id)
        self.refresh_order_status(order.order_id)
        return order

    def raise_customer_dispute(self, order_id: str, order_line_id: str, claimed_quantity: int, reason: str) -> Dispute:
        order = self.store.orders[order_id]
        line = self.store.order_lines[order_line_id]
        if line.order_id != order_id:
            raise ValueError("order line does not belong to order")

        dispute = Dispute(
            dispute_id=self.id_gen("dispute"),
            dispute_type="customer_dispute",
            source="customer",
            tenant_id=order.tenant_id,
            order_id=order_id,
            order_line_id=order_line_id,
            claimed_quantity=claimed_quantity,
            reason=reason,
        )
        dispute.history.append("customer_submitted")
        self.store.disputes[dispute.dispute_id] = dispute
        order.dispute_ids.append(dispute.dispute_id)
        line.disputed_quantity += claimed_quantity
        line.status = "disputed"
        self.store.emit("customer_dispute.created", dispute.dispute_id)
        self.refresh_order_status(order_id)
        return dispute

    def vendor_acknowledge(self, po_id: str, decisions: list[dict]) -> PurchaseOrder:
        po = self.store.purchase_orders[po_id]
        statuses = set()
        for decision in decisions:
            po_line = self.store.po_lines[decision["po_line_id"]]
            po_line.accepted_quantity = decision["accepted_quantity"]
            po_line.accepted_unit_price_minor = decision.get("proposed_unit_price_minor", po_line.unit_price_minor)
            statuses.add(decision["status"])

            order_line = self.store.order_lines[po_line.order_line_id]
            if decision["status"] == "accepted":
                po_line.status = "accepted"
                order_line.status = "procured"
                continue

            po_line.status = "disputed"
            order_line.status = "disputed"
            dispute = Dispute(
                dispute_id=self.id_gen("dispute"),
                dispute_type=decision["status"],
                source="vendor",
                tenant_id=po.tenant_id,
                order_id=po.order_id,
                vendor_id=po.vendor_id,
                po_id=po.po_id,
                po_line_id=po_line.po_line_id,
                order_line_id=po_line.order_line_id,
                requested_quantity=po_line.ordered_quantity,
                proposed_quantity=decision.get("accepted_quantity"),
                proposed_unit_price_minor=decision.get("proposed_unit_price_minor"),
                reason=decision.get("reason", ""),
            )
            dispute.history.append(f"vendor_submitted:{decision['status']}")
            self.store.disputes[dispute.dispute_id] = dispute
            po.dispute_ids.append(dispute.dispute_id)
            self.store.orders[po.order_id].dispute_ids.append(dispute.dispute_id)
            self.store.emit("vendor_dispute.created", dispute.dispute_id)

        if statuses == {"accepted"}:
            po.status = "accepted"
        elif "rejected" in statuses:
            po.status = "rejected"
        else:
            po.status = "accepted_with_changes"

        self.store.emit("purchase_order.acknowledged", po.po_id)
        self.refresh_order_status(po.order_id)
        return po

    def create_shipment(self, po_id: str, tracking_number: str, lines: list[dict]) -> Shipment:
        po = self.store.purchase_orders[po_id]
        shipment = Shipment(
            shipment_id=self.id_gen("shipment"),
            tenant_id=po.tenant_id,
            po_id=po.po_id,
            order_id=po.order_id,
            vendor_id=po.vendor_id,
            tracking_number=tracking_number,
        )
        self.store.shipments[shipment.shipment_id] = shipment

        for line_data in lines:
            po_line = self.store.po_lines[line_data["po_line_id"]]
            shipment_line = ShipmentLine(
                shipment_line_id=self.id_gen("shipment_line"),
                tenant_id=po.tenant_id,
                shipment_id=shipment.shipment_id,
                po_line_id=po_line.po_line_id,
                order_line_id=po_line.order_line_id,
                quantity=line_data["quantity"],
            )
            self.store.shipment_lines[shipment_line.shipment_line_id] = shipment_line
            shipment.line_ids.append(shipment_line.shipment_line_id)

            po_line.shipped_quantity += line_data["quantity"]
            target = po_line.accepted_quantity or po_line.ordered_quantity
            po_line.status = "shipped" if po_line.shipped_quantity >= target else "partially_shipped"

            order_line = self.store.order_lines[po_line.order_line_id]
            order_line.shipped_quantity += line_data["quantity"]
            order_line.status = "shipped" if order_line.shipped_quantity >= order_line.ordered_quantity else "partially_shipped"

        self.store.emit("shipment.created", shipment.shipment_id)
        self.refresh_order_status(po.order_id)
        return shipment

    def record_receipt(self, order_id: str, shipment_id: str, lines: list[dict]) -> GoodsReceipt:
        receipt = GoodsReceipt(
            receipt_id=self.id_gen("receipt"),
            tenant_id=self.store.orders[order_id].tenant_id,
            order_id=order_id,
            shipment_id=shipment_id,
        )
        self.store.receipts[receipt.receipt_id] = receipt
        self.store.orders[order_id].receipt_ids.append(receipt.receipt_id)

        for line_data in lines:
            shipment_line = self.store.shipment_lines[line_data["shipment_line_id"]]
            receipt_line = GoodsReceiptLine(
                receipt_line_id=self.id_gen("receipt_line"),
                tenant_id=self.store.orders[order_id].tenant_id,
                receipt_id=receipt.receipt_id,
                shipment_line_id=shipment_line.shipment_line_id,
                order_line_id=shipment_line.order_line_id,
                expected_quantity=shipment_line.quantity,
                received_quantity=line_data["received_quantity"],
                condition=line_data.get("condition", "good"),
            )
            self.store.receipt_lines[receipt_line.receipt_line_id] = receipt_line
            receipt.line_ids.append(receipt_line.receipt_line_id)

            po_line = self.store.po_lines[shipment_line.po_line_id]
            order_line = self.store.order_lines[shipment_line.order_line_id]
            po_line.received_quantity += receipt_line.received_quantity
            order_line.received_quantity += receipt_line.received_quantity

            if receipt_line.received_quantity < receipt_line.expected_quantity or receipt_line.condition != "good":
                dispute = Dispute(
                    dispute_id=self.id_gen("dispute"),
                    dispute_type="customer_quantity_dispute" if receipt_line.received_quantity < receipt_line.expected_quantity else "customer_condition_dispute",
                    source="customer",
                    tenant_id=self.store.orders[order_id].tenant_id,
                    order_id=order_id,
                    order_line_id=shipment_line.order_line_id,
                    claimed_quantity=receipt_line.expected_quantity - receipt_line.received_quantity,
                    reason="customer receipt mismatch",
                )
                dispute.history.append("customer_submitted")
                self.store.disputes[dispute.dispute_id] = dispute
                self.store.orders[order_id].dispute_ids.append(dispute.dispute_id)
                order_line.status = "disputed"
                self.store.emit("customer_dispute.created", dispute.dispute_id)
            else:
                target = po_line.accepted_quantity or po_line.ordered_quantity
                po_line.status = "received" if po_line.received_quantity >= target else "partially_received"
                order_line.status = "received" if order_line.received_quantity >= order_line.ordered_quantity else "partially_received"

        self.store.emit("goods_receipt.recorded", receipt.receipt_id)
        self.refresh_order_status(order_id)
        return receipt

    def resolve_dispute(self, dispute_id: str, resolution: str) -> Dispute:
        dispute = self.store.disputes[dispute_id]
        dispute.status = "resolved"
        dispute.resolution = resolution
        dispute.history.append(f"resolved:{resolution}")
        dispute.updated_at = utc_now()

        if dispute.source == "vendor" and dispute.po_line_id:
            po_line = self.store.po_lines[dispute.po_line_id]
            order_line = self.store.order_lines[po_line.order_line_id]
            if resolution == "accepted_vendor_terms":
                if dispute.proposed_quantity is not None:
                    po_line.accepted_quantity = dispute.proposed_quantity
                    order_line.ordered_quantity = dispute.proposed_quantity
                if dispute.proposed_unit_price_minor is not None:
                    po_line.accepted_unit_price_minor = dispute.proposed_unit_price_minor
                po_line.status = "accepted"
                order_line.status = "procured"
            else:
                po_line.status = "rejected"
                order_line.status = "disputed"
            if dispute.po_id:
                po = self.store.purchase_orders[dispute.po_id]
                po.status = "accepted" if resolution == "accepted_vendor_terms" else "rejected"

        if dispute.source == "customer" and dispute.order_line_id:
            line = self.store.order_lines[dispute.order_line_id]
            if resolution in {"accept_customer_claim", "commercial_settlement"}:
                line.status = "completed"
            elif resolution in {"customer_claim_rejected", "close_as_received"}:
                line.status = "received"

        self.store.emit("dispute.resolved", dispute.dispute_id)
        self.refresh_order_status(dispute.order_id)
        return dispute

    def create_invoice(self, tenant_id: str, po_id: str, invoice_number: str, lines: list[dict]) -> Invoice:
        invoice = Invoice(
            invoice_id=self.id_gen("invoice"),
            tenant_id=tenant_id,
            po_id=po_id,
            invoice_number=invoice_number,
        )
        self.store.invoices[invoice.invoice_id] = invoice

        for line in lines:
            po_line = self.store.po_lines[line["po_line_id"]]
            expected_qty = po_line.accepted_quantity or po_line.ordered_quantity
            expected_price = po_line.accepted_unit_price_minor or po_line.unit_price_minor
            receipt_qty = po_line.received_quantity

            match_status = "mismatch"
            if (
                line["billed_quantity"] == expected_qty
                and line["billed_unit_price_minor"] == expected_price
                and receipt_qty >= line["billed_quantity"]
            ):
                match_status = "matched"
            elif line["billed_quantity"] > receipt_qty:
                match_status = "receipt_mismatch"
            elif line["billed_quantity"] != expected_qty or line["billed_unit_price_minor"] != expected_price:
                match_status = "po_mismatch"

            invoice_line = InvoiceLine(
                invoice_line_id=self.id_gen("invoice_line"),
                tenant_id=tenant_id,
                invoice_id=invoice.invoice_id,
                po_line_id=line["po_line_id"],
                billed_quantity=line["billed_quantity"],
                billed_unit_price_minor=line["billed_unit_price_minor"],
                match_status=match_status,
            )
            self.store.invoice_lines[invoice_line.invoice_line_id] = invoice_line
            invoice.line_ids.append(invoice_line.invoice_line_id)

        invoice.status = "matched" if all(self.store.invoice_lines[lid].match_status == "matched" for lid in invoice.line_ids) else "mismatch"
        self.store.emit("invoice.received", invoice.invoice_id)
        return invoice

    def cancel_order_line(self, order_id: str, order_line_id: str, reason: str) -> CustomerOrderLine:
        line = self.store.order_lines[order_line_id]
        if line.shipped_quantity or line.received_quantity:
            raise ValueError("cannot cancel shipped or received line")
        line.status = "cancelled"
        line.allocated_quantity = 0

        for allocation in self.store.allocations.values():
            if allocation.order_line_id == order_line_id:
                allocation.status = "cancelled"
                allocation.reason = reason

        for po in self.store.purchase_orders.values():
            if po.order_id != order_id:
                continue
            for po_line_id in po.line_ids:
                po_line = self.store.po_lines[po_line_id]
                if po_line.order_line_id == order_line_id:
                    po_line.status = "cancelled"

        self.store.emit("customer_order.line_cancelled", order_line_id)
        self.refresh_order_status(order_id)
        return line

    def reallocate_order_line(self, order_id: str, order_line_id: str, new_vendor_id: str, reason: str) -> PurchaseOrder:
        line = self.store.order_lines[order_line_id]
        if line.shipped_quantity or line.received_quantity:
            raise ValueError("cannot reallocate shipped or received line")

        for allocation in self.store.allocations.values():
            if allocation.order_line_id == order_line_id and allocation.status == "allocated":
                allocation.status = "reallocated"
                allocation.reason = reason

        for po in self.store.purchase_orders.values():
            if po.order_id != order_id:
                continue
            for po_line_id in po.line_ids:
                po_line = self.store.po_lines[po_line_id]
                if po_line.order_line_id == order_line_id and po_line.status not in {"cancelled", "received", "shipped"}:
                    po_line.status = "reallocated"

        line.vendor_id = new_vendor_id
        line.status = "allocated"
        allocation = VendorAllocation(
            allocation_id=self.id_gen("allocation"),
            tenant_id=self.store.orders[order_id].tenant_id,
            order_id=order_id,
            order_line_id=order_line_id,
            vendor_id=new_vendor_id,
            quantity=line.ordered_quantity,
            reason=reason,
        )
        self.store.allocations[allocation.allocation_id] = allocation

        po = PurchaseOrder(
            po_id=self.id_gen("po"),
            tenant_id=self.store.orders[order_id].tenant_id,
            po_number=f"PO-{len(self.store.purchase_orders) + 1:06d}",
            order_id=order_id,
            vendor_id=new_vendor_id,
            ship_to=self.store.orders[order_id].ship_to,
        )
        self.store.purchase_orders[po.po_id] = po
        self.store.orders[order_id].po_ids.append(po.po_id)

        po_line = PurchaseOrderLine(
            po_line_id=self.id_gen("po_line"),
            tenant_id=po.tenant_id,
            po_id=po.po_id,
            order_line_id=order_line_id,
            vendor_id=new_vendor_id,
            sku=line.sku,
            description=line.description,
            ordered_quantity=line.ordered_quantity,
            unit_price_minor=line.unit_price_minor,
            accepted_unit_price_minor=line.unit_price_minor,
        )
        self.store.po_lines[po_line.po_line_id] = po_line
        po.line_ids.append(po_line.po_line_id)

        self.store.emit("customer_order.line_reallocated", order_line_id)
        self.refresh_order_status(order_id)
        return po

    def finalize_order(self, order_id: str) -> CustomerOrder:
        order = self.store.orders[order_id]
        for line_id in order.line_ids:
            line = self.store.order_lines[line_id]
            if line.status in {"received", "procured", "shipped", "cancelled"}:
                line.status = "completed"
        self.refresh_order_status(order_id)
        return order

    def evaluate_slas(self) -> list[SLARecord]:
        now = utc_now()
        breached = []
        for sla in self.store.sla_records.values():
            due_at = sla.due_at if sla.due_at.tzinfo else sla.due_at.replace(tzinfo=timezone.utc)
            if sla.status == "pending" and now >= due_at:
                sla.status = "breached"
                breached.append(sla)
                self.store.emit("sla.breached", sla.sla_id)
        return breached

    def refresh_order_status(self, order_id: str) -> CustomerOrder:
        order = self.store.orders[order_id]
        lines = [self.store.order_lines[line_id] for line_id in order.line_ids]
        counts = Counter(line.status for line in lines)

        if lines and all(line.status == "cancelled" for line in lines):
            order.status = "cancelled"
        elif lines and all(line.status in {"completed", "cancelled"} for line in lines):
            order.status = "completed"
        elif counts["disputed"] > 0:
            order.status = "partially_disputed" if counts["completed"] or counts["received"] else "disputed"
        elif any(line.received_quantity > 0 for line in lines):
            order.status = "partially_received"
            if all(line.received_quantity >= line.ordered_quantity for line in lines):
                order.status = "received"
        elif any(line.shipped_quantity > 0 for line in lines):
            order.status = "partially_shipped"
            if all(line.shipped_quantity >= line.ordered_quantity for line in lines):
                order.status = "shipped"
        elif order.po_ids:
            order.status = "fully_procured"
        else:
            order.status = "allocating"
        return order

    def three_way_match_report(self, invoice_id: str) -> dict:
        invoice = self.store.invoices[invoice_id]
        po = self.store.purchase_orders[invoice.po_id]
        findings = []
        all_matched = True

        for invoice_line_id in invoice.line_ids:
            invoice_line = self.store.invoice_lines[invoice_line_id]
            po_line = self.store.po_lines[invoice_line.po_line_id]
            expected_quantity = po_line.accepted_quantity or po_line.ordered_quantity
            expected_price = po_line.accepted_unit_price_minor or po_line.unit_price_minor
            receipt_quantity = po_line.received_quantity

            quantity_match = invoice_line.billed_quantity == expected_quantity
            price_match = invoice_line.billed_unit_price_minor == expected_price
            receipt_match = receipt_quantity >= invoice_line.billed_quantity

            line_match = quantity_match and price_match and receipt_match
            if not line_match:
                all_matched = False

            findings.append(
                {
                    "invoice_line_id": invoice_line.invoice_line_id,
                    "po_line_id": po_line.po_line_id,
                    "sku": po_line.sku,
                    "invoice_quantity": invoice_line.billed_quantity,
                    "po_quantity": expected_quantity,
                    "received_quantity": receipt_quantity,
                    "invoice_unit_price_minor": invoice_line.billed_unit_price_minor,
                    "po_unit_price_minor": expected_price,
                    "quantity_match": quantity_match,
                    "price_match": price_match,
                    "receipt_match": receipt_match,
                    "line_match": line_match,
                }
            )

        return {
            "invoice_id": invoice.invoice_id,
            "invoice_number": invoice.invoice_number,
            "po_id": po.po_id,
            "order_id": po.order_id,
            "overall_status": "matched" if all_matched else "mismatch",
            "findings": findings,
        }
