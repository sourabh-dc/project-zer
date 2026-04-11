from __future__ import annotations

from collections import Counter

from supply_v2.models import CustomerOrder, CustomerOrderLine
from supply_v2.store import InMemoryStore


class OrderService:
    def __init__(self, store: InMemoryStore, id_gen) -> None:
        self.store = store
        self.id_gen = id_gen

    def place_order(self, tenant_id: str, customer_id: str, ship_to: dict, items: list[dict]) -> CustomerOrder:
        order_id = self.id_gen("order")
        order_number = f"ORD-{len(self.store.orders) + 1:06d}"
        order = CustomerOrder(
            order_id=order_id,
            tenant_id=tenant_id,
            order_number=order_number,
            customer_id=customer_id,
            ship_to=ship_to,
            status="allocating",
        )
        self.store.orders[order_id] = order

        for item in items:
            line_id = self.id_gen("order_line")
            line = CustomerOrderLine(
                order_line_id=line_id,
                tenant_id=tenant_id,
                order_id=order_id,
                vendor_id=item["vendor_id"],
                sku=item["sku"],
                description=item["description"],
                ordered_quantity=item["quantity"],
                unit_price_minor=item["unit_price_minor"],
            )
            self.store.order_lines[line_id] = line
            order.line_ids.append(line_id)

        order.event_log.append("customer_order.placed")
        self.store.emit("customer_order.placed", order.order_id)
        return order

    def refresh_order_status(self, order_id: str) -> CustomerOrder:
        order = self.store.orders[order_id]
        lines = [self.store.order_lines[line_id] for line_id in order.line_ids]
        status_counts = Counter(line.status for line in lines)

        if lines and all(line.status == "cancelled" for line in lines):
            order.status = "cancelled"
        elif lines and all(line.status in {"completed", "cancelled"} for line in lines):
            order.status = "completed"
        elif status_counts["disputed"] > 0:
            order.status = "partially_disputed" if status_counts["completed"] or status_counts["received"] else "disputed"
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
