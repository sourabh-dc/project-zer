from supply_v2 import SupplyPlatform


def main() -> None:
    platform = SupplyPlatform()
    platform.register_vendor("tenant_demo", "vendor_acme", "Acme Supplies", "ops@acme.test")
    platform.register_vendor("tenant_demo", "vendor_beta", "Beta Industrial", "sales@beta.test")

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_demo",
        ship_to={"line1": "500 Demo Street", "city": "London"},
        items=[
            {
                "vendor_id": "vendor_acme",
                "sku": "PEN-001",
                "description": "Blue Pen",
                "quantity": 10,
                "unit_price_minor": 100,
            },
            {
                "vendor_id": "vendor_beta",
                "sku": "MUG-002",
                "description": "Coffee Mug",
                "quantity": 5,
                "unit_price_minor": 300,
            },
        ],
    )

    acme_po = next(po_id for po_id in order.po_ids if platform.store.purchase_orders[po_id].vendor_id == "vendor_acme")
    beta_po = next(po_id for po_id in order.po_ids if platform.store.purchase_orders[po_id].vendor_id == "vendor_beta")

    acme_po_line = platform.store.purchase_orders[acme_po].line_ids[0]
    beta_po_line = platform.store.purchase_orders[beta_po].line_ids[0]

    platform.vendor_acknowledge(
        acme_po,
        [
            {
                "po_line_id": acme_po_line,
                "accepted_quantity": 10,
                "status": "accepted",
            }
        ],
    )

    platform.vendor_acknowledge(
        beta_po,
        [
            {
                "po_line_id": beta_po_line,
                "accepted_quantity": 4,
                "status": "quantity_changed",
                "reason": "one unit unavailable",
            }
        ],
    )

    beta_dispute_id = platform.store.purchase_orders[beta_po].dispute_ids[0]
    platform.resolve_vendor_dispute(beta_dispute_id)

    acme_shipment = platform.vendor_create_shipment(
        acme_po,
        tracking_number="TRACK-ACME-1",
        lines=[{"po_line_id": acme_po_line, "quantity": 10}],
    )
    beta_shipment = platform.vendor_create_shipment(
        beta_po,
        tracking_number="TRACK-BETA-1",
        lines=[{"po_line_id": beta_po_line, "quantity": 4}],
    )

    platform.customer_record_receipt(
        order_id=order.order_id,
        shipment_id=acme_shipment.shipment_id,
        lines=[{"shipment_line_id": acme_shipment.line_ids[0], "received_quantity": 10, "condition": "good"}],
    )
    platform.customer_record_receipt(
        order_id=order.order_id,
        shipment_id=beta_shipment.shipment_id,
        lines=[{"shipment_line_id": beta_shipment.line_ids[0], "received_quantity": 3, "condition": "good"}],
    )

    customer_dispute_id = next(
        dispute.dispute_id
        for dispute in platform.store.disputes.values()
        if dispute.source == "customer"
    )
    platform.resolve_customer_dispute(customer_dispute_id, "refund_issued")
    platform.finalize_order(order.order_id)

    print(f"order={order.order_number} status={platform.store.orders[order.order_id].status}")
    print(f"po_count={len(order.po_ids)} notifications={len(platform.store.notifications)} disputes={len(platform.store.disputes)}")
    for po_id in order.po_ids:
        po = platform.store.purchase_orders[po_id]
        print(f"{po.po_number} vendor={po.vendor_id} status={po.status}")
    print(f"events={len(platform.store.events)}")


if __name__ == "__main__":
    main()
