from __future__ import annotations

from supply_v2.models import GoodsReceipt, GoodsReceiptLine, Shipment, ShipmentLine
from supply_v2.store import InMemoryStore


class FulfilmentService:
    def __init__(self, store: InMemoryStore, id_gen) -> None:
        self.store = store
        self.id_gen = id_gen

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
            po_line.status = "shipped" if po_line.shipped_quantity >= (po_line.accepted_quantity or po_line.ordered_quantity) else "partially_shipped"

            order_line = self.store.order_lines[po_line.order_line_id]
            order_line.shipped_quantity += line_data["quantity"]
            order_line.status = "shipped" if order_line.shipped_quantity >= order_line.ordered_quantity else "partially_shipped"

        po.status = "shipped" if all(
            self.store.po_lines[line_id].shipped_quantity >= (self.store.po_lines[line_id].accepted_quantity or self.store.po_lines[line_id].ordered_quantity)
            for line_id in po.line_ids
        ) else "partially_shipped"
        self.store.emit("shipment.created", shipment.shipment_id)
        return shipment

    def record_receipt(self, order_id: str, shipment_id: str, lines: list[dict], dispute_service) -> GoodsReceipt:
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

            order_line = self.store.order_lines[shipment_line.order_line_id]
            order_line.received_quantity += receipt_line.received_quantity

            po_line = self.store.po_lines[shipment_line.po_line_id]
            po_line.received_quantity += receipt_line.received_quantity

            if receipt_line.received_quantity < receipt_line.expected_quantity:
                dispute_service.create_customer_dispute(
                    order_id=order_id,
                    order_line_id=shipment_line.order_line_id,
                    claimed_quantity=receipt_line.expected_quantity - receipt_line.received_quantity,
                    reason="customer reported shortage",
                )
            elif receipt_line.condition != "good":
                dispute_service.create_customer_dispute(
                    order_id=order_id,
                    order_line_id=shipment_line.order_line_id,
                    claimed_quantity=receipt_line.received_quantity,
                    reason=f"customer reported {receipt_line.condition}",
                )
            else:
                target_qty = po_line.accepted_quantity or po_line.ordered_quantity
                po_line.status = "received" if po_line.received_quantity >= target_qty else "partially_received"
                order_line.status = "received" if order_line.received_quantity >= order_line.ordered_quantity else "partially_received"

        self.store.emit("goods_receipt.recorded", receipt.receipt_id)
        return receipt
