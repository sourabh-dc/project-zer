from __future__ import annotations

from collections import defaultdict

from supply_v2.models import PurchaseOrder, PurchaseOrderLine, VendorAllocation
from supply_v2.store import InMemoryStore


class ProcurementService:
    def __init__(self, store: InMemoryStore, id_gen, notification_service) -> None:
        self.store = store
        self.id_gen = id_gen
        self.notification_service = notification_service

    def allocate_order(self, order_id: str) -> list[PurchaseOrder]:
        order = self.store.orders[order_id]
        grouped: dict[str, list] = defaultdict(list)

        for line_id in order.line_ids:
            line = self.store.order_lines[line_id]
            allocation = VendorAllocation(
                allocation_id=self.id_gen("allocation"),
                tenant_id=order.tenant_id,
                order_id=order.order_id,
                order_line_id=line.order_line_id,
                vendor_id=line.vendor_id,
                quantity=line.ordered_quantity,
            )
            self.store.allocations[allocation.allocation_id] = allocation
            grouped[line.vendor_id].append(line)
            line.allocated_quantity = line.ordered_quantity
            line.status = "allocated"

        created: list[PurchaseOrder] = []
        for vendor_id, vendor_lines in grouped.items():
            po = self._queue_po(order, vendor_id, vendor_lines)
            created.append(po)

        order.event_log.append("customer_order.procured")
        self.store.emit("customer_order.procured", order.order_id)
        return created

    def _queue_po(self, order, vendor_id: str, vendor_lines: list) -> PurchaseOrder:
        po_id = self.id_gen("po")
        po = PurchaseOrder(
            po_id=po_id,
            tenant_id=order.tenant_id,
            po_number=f"PO-{len(self.store.purchase_orders) + 1:06d}",
            order_id=order.order_id,
            vendor_id=vendor_id,
            ship_to=order.ship_to,
        )
        self.store.purchase_orders[po.po_id] = po
        order.po_ids.append(po.po_id)

        for line in vendor_lines:
            po_line = PurchaseOrderLine(
                po_line_id=self.id_gen("po_line"),
                tenant_id=order.tenant_id,
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
        notification = self.notification_service.queue_vendor_po_email(
            tenant_id=order.tenant_id,
            vendor_id=vendor_id,
            po_id=po.po_id,
            target_email=vendor.primary_email,
            payload={"po_number": po.po_number, "line_count": len(po.line_ids)},
        )
        po.event_log.append("purchase_order.issued")
        self.store.emit("purchase_order.issued", po.po_id)
        self.store.emit("vendor_notification.queued", notification.notification_id)
        return po

    def acknowledge_po(
        self,
        po_id: str,
        decisions: list[dict],
        dispute_service,
    ) -> PurchaseOrder:
        po = self.store.purchase_orders[po_id]
        statuses: set[str] = set()

        for decision in decisions:
            po_line = self.store.po_lines[decision["po_line_id"]]
            po_line.accepted_quantity = decision["accepted_quantity"]
            po_line.accepted_unit_price_minor = decision.get("proposed_unit_price_minor", po_line.unit_price_minor)
            decision_status = decision["status"]
            statuses.add(decision_status)

            if decision_status == "accepted":
                po_line.status = "accepted"
                order_line = self.store.order_lines[po_line.order_line_id]
                order_line.status = "procured"
                continue

            po_line.status = "disputed"
            order_line = self.store.order_lines[po_line.order_line_id]
            order_line.status = "disputed"
            dispute = dispute_service.create_vendor_dispute(
                po=po,
                po_line=po_line,
                dispute_type=decision_status,
                proposed_quantity=decision.get("accepted_quantity"),
                proposed_unit_price_minor=decision.get("proposed_unit_price_minor"),
                reason=decision.get("reason", ""),
            )
            po.dispute_ids.append(dispute.dispute_id)

        if statuses == {"accepted"}:
            po.status = "accepted"
        elif "rejected" in statuses:
            po.status = "rejected"
        else:
            po.status = "accepted_with_changes"

        po.event_log.append("purchase_order.acknowledged")
        self.store.emit("purchase_order.acknowledged", po.po_id)
        return po

    def cancel_order_line(self, order_id: str, order_line_id: str, reason: str):
        order = self.store.orders[order_id]
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
            active_line_statuses = [self.store.po_lines[item].status for item in po.line_ids]
            if active_line_statuses and all(status == "cancelled" for status in active_line_statuses):
                po.status = "cancelled"

        order.event_log.append(f"customer_order.line_cancelled:{order_line_id}")
        self.store.emit("customer_order.line_cancelled", order_line_id)
        return line

    def reallocate_order_line(self, order_id: str, order_line_id: str, new_vendor_id: str, reason: str) -> PurchaseOrder:
        order = self.store.orders[order_id]
        line = self.store.order_lines[order_line_id]
        if line.shipped_quantity or line.received_quantity:
            raise ValueError("cannot reallocate shipped or received line")

        old_vendor_id = line.vendor_id
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
            active_line_statuses = [self.store.po_lines[item].status for item in po.line_ids]
            if active_line_statuses and all(status in {"reallocated", "cancelled"} for status in active_line_statuses):
                po.status = "reallocated"

        line.vendor_id = new_vendor_id
        line.status = "allocated"
        line.allocated_quantity = line.ordered_quantity
        allocation = VendorAllocation(
            allocation_id=self.id_gen("allocation"),
            tenant_id=order.tenant_id,
            order_id=order_id,
            order_line_id=order_line_id,
            vendor_id=new_vendor_id,
            quantity=line.ordered_quantity,
            reason=reason,
        )
        self.store.allocations[allocation.allocation_id] = allocation
        new_po = self._queue_po(order, new_vendor_id, [line])
        order.event_log.append(f"customer_order.line_reallocated:{order_line_id}:{old_vendor_id}:{new_vendor_id}")
        self.store.emit("customer_order.line_reallocated", order_line_id)
        return new_po
