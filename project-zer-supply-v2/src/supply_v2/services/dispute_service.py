from supply_v2.models import Dispute
from supply_v2.store import InMemoryStore


class DisputeService:
    def __init__(self, store: InMemoryStore, id_gen) -> None:
        self.store = store
        self.id_gen = id_gen

    def create_vendor_dispute(
        self,
        *,
        po,
        po_line,
        dispute_type: str,
        proposed_quantity,
        proposed_unit_price_minor,
        reason: str,
    ) -> Dispute:
        order_line = self.store.order_lines[po_line.order_line_id]
        dispute = Dispute(
            dispute_id=self.id_gen("dispute"),
            dispute_type=dispute_type,
            source="vendor",
            tenant_id=po.tenant_id,
            order_id=po.order_id,
            vendor_id=po.vendor_id,
            po_id=po.po_id,
            po_line_id=po_line.po_line_id,
            order_line_id=po_line.order_line_id,
            requested_quantity=po_line.ordered_quantity,
            proposed_quantity=proposed_quantity,
            proposed_unit_price_minor=proposed_unit_price_minor,
            reason=reason,
        )
        dispute.history.append(f"vendor_submitted:{dispute_type}")
        self.store.disputes[dispute.dispute_id] = dispute
        self.store.orders[po.order_id].dispute_ids.append(dispute.dispute_id)
        order_line.disputed_quantity = proposed_quantity or 0
        self.store.emit("vendor_dispute.created", dispute.dispute_id)
        return dispute

    def create_customer_dispute(
        self,
        *,
        order_id: str,
        order_line_id: str,
        claimed_quantity: int,
        reason: str,
    ) -> Dispute:
        line = self.store.order_lines[order_line_id]
        dispute = Dispute(
            dispute_id=self.id_gen("dispute"),
            dispute_type="customer_quantity_dispute",
            source="customer",
            tenant_id=self.store.orders[order_id].tenant_id,
            order_id=order_id,
            order_line_id=order_line_id,
            claimed_quantity=claimed_quantity,
            reason=reason,
        )
        dispute.history.append("customer_submitted:customer_quantity_dispute")
        self.store.disputes[dispute.dispute_id] = dispute
        self.store.orders[order_id].dispute_ids.append(dispute.dispute_id)
        line.status = "disputed"
        self.store.emit("customer_dispute.created", dispute.dispute_id)
        return dispute

    def resolve_accept_vendor_terms(self, dispute_id: str) -> Dispute:
        dispute = self.store.disputes[dispute_id]
        dispute.status = "resolved"
        dispute.resolution = "accepted_vendor_terms"
        dispute.history.append("resolved:accepted_vendor_terms")
        dispute.updated_at = dispute.created_at

        if dispute.po_line_id:
            po_line = self.store.po_lines[dispute.po_line_id]
            order_line = self.store.order_lines[po_line.order_line_id]
            if dispute.proposed_quantity is not None:
                po_line.accepted_quantity = dispute.proposed_quantity
                order_line.ordered_quantity = dispute.proposed_quantity
            if dispute.proposed_unit_price_minor is not None:
                po_line.accepted_unit_price_minor = dispute.proposed_unit_price_minor
            po_line.status = "accepted"
            order_line.status = "procured"

        if dispute.po_id:
            po = self.store.purchase_orders[dispute.po_id]
            if all(self.store.po_lines[line_id].status == "accepted" for line_id in po.line_ids):
                po.status = "accepted"

        self.store.emit("dispute.resolved", dispute.dispute_id)
        return dispute

    def resolve_reject_vendor_terms(self, dispute_id: str) -> Dispute:
        dispute = self.store.disputes[dispute_id]
        dispute.status = "resolved"
        dispute.resolution = "rejected_vendor_terms"
        dispute.history.append("resolved:rejected_vendor_terms")

        if dispute.po_line_id:
            po_line = self.store.po_lines[dispute.po_line_id]
            order_line = self.store.order_lines[po_line.order_line_id]
            po_line.status = "rejected"
            order_line.status = "disputed"

        if dispute.po_id:
            po = self.store.purchase_orders[dispute.po_id]
            po.status = "rejected"

        self.store.emit("dispute.resolved", dispute.dispute_id)
        return dispute

    def resolve_customer_shortage(self, dispute_id: str, resolution: str) -> Dispute:
        dispute = self.store.disputes[dispute_id]
        dispute.status = "resolved"
        dispute.resolution = resolution
        dispute.history.append(f"resolved:{resolution}")
        dispute.updated_at = dispute.created_at

        if dispute.order_line_id:
            line = self.store.order_lines[dispute.order_line_id]
            if resolution in {"accept_customer_claim", "commercial_settlement"}:
                line.status = "completed"
            elif resolution in {"customer_claim_rejected", "close_as_received"}:
                line.status = "received"
            else:
                line.status = "disputed"

        self.store.emit("dispute.resolved", dispute.dispute_id)
        return dispute
