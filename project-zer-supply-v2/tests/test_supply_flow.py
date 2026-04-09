from supply_v2 import SupplyPlatform


def _build_platform() -> SupplyPlatform:
    platform = SupplyPlatform()
    platform.register_vendor("tenant_demo", "vendor_acme", "Acme Supplies", "ops@acme.test")
    platform.register_vendor("tenant_demo", "vendor_beta", "Beta Industrial", "sales@beta.test")
    return platform


def test_multivendor_procurement_split_and_notifications() -> None:
    platform = _build_platform()

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_001",
        ship_to={"line1": "221B Baker Street", "city": "London"},
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
                "sku": "CHAIR-009",
                "description": "Desk Chair",
                "quantity": 2,
                "unit_price_minor": 5000,
            },
        ],
    )

    assert len(order.po_ids) == 2
    assert order.status == "fully_procured"
    assert len(platform.store.notifications) == 2
    assert all(notification.status == "queued" for notification in platform.store.notifications.values())


def test_vendor_price_dispute_resolution_flow() -> None:
    platform = _build_platform()

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_002",
        ship_to={"line1": "42 Fleet Street", "city": "London"},
        items=[
            {
                "vendor_id": "vendor_acme",
                "sku": "LAPTOP-001",
                "description": "Laptop",
                "quantity": 1,
                "unit_price_minor": 100000,
            }
        ],
    )
    po_id = order.po_ids[0]
    po = platform.store.purchase_orders[po_id]
    po_line_id = po.line_ids[0]

    platform.vendor_acknowledge(
        po_id,
        [
            {
                "po_line_id": po_line_id,
                "accepted_quantity": 1,
                "proposed_unit_price_minor": 110000,
                "status": "price_changed",
                "reason": "supplier cost increased",
            }
        ],
    )

    assert po.status == "accepted_with_changes"
    dispute_id = po.dispute_ids[0]
    dispute = platform.store.disputes[dispute_id]
    assert dispute.proposed_unit_price_minor == 110000
    assert platform.store.order_lines[dispute.order_line_id].status == "disputed"

    platform.resolve_vendor_dispute(dispute_id)

    assert dispute.status == "resolved"
    assert po.status == "accepted"
    assert platform.store.po_lines[po_line_id].accepted_unit_price_minor == 110000
    assert platform.store.order_lines[dispute.order_line_id].status == "procured"


def test_customer_short_receipt_dispute_flow() -> None:
    platform = _build_platform()

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_003",
        ship_to={"line1": "10 Downing Street", "city": "London"},
        items=[
            {
                "vendor_id": "vendor_beta",
                "sku": "MUG-002",
                "description": "Coffee Mug",
                "quantity": 5,
                "unit_price_minor": 300,
            }
        ],
    )
    po_id = order.po_ids[0]
    po = platform.store.purchase_orders[po_id]
    po_line_id = po.line_ids[0]

    platform.vendor_acknowledge(
        po_id,
        [
            {
                "po_line_id": po_line_id,
                "accepted_quantity": 5,
                "status": "accepted",
            }
        ],
    )

    shipment = platform.vendor_create_shipment(
        po_id,
        tracking_number="TRACK-001",
        lines=[{"po_line_id": po_line_id, "quantity": 5}],
    )

    platform.customer_record_receipt(
        order_id=order.order_id,
        shipment_id=shipment.shipment_id,
        lines=[{"shipment_line_id": shipment.line_ids[0], "received_quantity": 3, "condition": "good"}],
    )

    disputes = [d for d in platform.store.disputes.values() if d.order_id == order.order_id and d.source == "customer"]
    assert len(disputes) == 1
    dispute = disputes[0]
    assert dispute.claimed_quantity == 2
    assert platform.store.orders[order.order_id].status in {"disputed", "partially_disputed"}

    platform.resolve_customer_dispute(dispute.dispute_id, "accept_customer_claim")
    platform.finalize_order(order.order_id)

    assert dispute.status == "resolved"
    assert platform.store.order_lines[dispute.order_line_id].status == "completed"
    assert platform.store.orders[order.order_id].status == "completed"


def test_end_to_end_simulation_summary() -> None:
    platform = _build_platform()

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_004",
        ship_to={"line1": "1600 Pennsylvania Ave", "city": "Washington"},
        items=[
            {
                "vendor_id": "vendor_acme",
                "sku": "PAPER-001",
                "description": "A4 Paper",
                "quantity": 20,
                "unit_price_minor": 50,
            },
            {
                "vendor_id": "vendor_beta",
                "sku": "INK-010",
                "description": "Printer Ink",
                "quantity": 4,
                "unit_price_minor": 2500,
            },
        ],
    )

    for po_id in order.po_ids:
        po = platform.store.purchase_orders[po_id]
        decisions = [
            {
                "po_line_id": line_id,
                "accepted_quantity": platform.store.po_lines[line_id].ordered_quantity,
                "status": "accepted",
            }
            for line_id in po.line_ids
        ]
        platform.vendor_acknowledge(po_id, decisions)
        shipment = platform.vendor_create_shipment(
            po_id,
            tracking_number=f"TRACK-{po.po_number}",
            lines=[
                {
                    "po_line_id": line_id,
                    "quantity": platform.store.po_lines[line_id].ordered_quantity,
                }
                for line_id in po.line_ids
            ],
        )
        platform.customer_record_receipt(
            order_id=order.order_id,
            shipment_id=shipment.shipment_id,
            lines=[
                {
                    "shipment_line_id": shipment_line_id,
                    "received_quantity": platform.store.shipment_lines[shipment_line_id].quantity,
                    "condition": "good",
                }
                for shipment_line_id in shipment.line_ids
            ],
        )

    platform.finalize_order(order.order_id)

    assert platform.store.orders[order.order_id].status == "completed"
    assert not [d for d in platform.store.disputes.values() if d.order_id == order.order_id]
    assert len(platform.store.events) >= 10


def test_invoice_matching_and_sla_breach() -> None:
    platform = _build_platform()

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_005",
        ship_to={"line1": "5 Match Road", "city": "London"},
        items=[
            {
                "vendor_id": "vendor_acme",
                "sku": "MATCH-001",
                "description": "Matcher",
                "quantity": 2,
                "unit_price_minor": 800,
            }
        ],
    )
    po_id = order.po_ids[0]
    po = platform.store.purchase_orders[po_id]
    po_line_id = po.line_ids[0]
    platform.vendor_acknowledge(
        po_id,
        [{"po_line_id": po_line_id, "accepted_quantity": 2, "status": "accepted"}],
    )
    shipment = platform.vendor_create_shipment(
        po_id,
        tracking_number="TRACK-MATCH",
        lines=[{"po_line_id": po_line_id, "quantity": 2}],
    )
    platform.customer_record_receipt(
        order_id=order.order_id,
        shipment_id=shipment.shipment_id,
        lines=[{"shipment_line_id": shipment.line_ids[0], "received_quantity": 2, "condition": "good"}],
    )

    invoice = platform.create_invoice(
        tenant_id="tenant_demo",
        po_id=po_id,
        invoice_number="INV-001",
        lines=[{"po_line_id": po_line_id, "billed_quantity": 2, "billed_unit_price_minor": 800}],
    )
    assert invoice.status == "matched"

    sla = next(iter(platform.store.sla_records.values()))
    sla.due_at = sla.created_at
    breached = platform.evaluate_slas()

    assert len(breached) == 1
    assert breached[0].status == "breached"


def test_reallocate_and_cancel_lines() -> None:
    platform = _build_platform()
    platform.register_vendor("tenant_demo", "vendor_gamma", "Gamma Supplies", "gamma@test.com")

    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_006",
        ship_to={"line1": "7 Ops Street", "city": "London"},
        items=[
            {
                "vendor_id": "vendor_acme",
                "sku": "REALLOC-1",
                "description": "Reallocate me",
                "quantity": 3,
                "unit_price_minor": 100,
            },
            {
                "vendor_id": "vendor_beta",
                "sku": "CANCEL-1",
                "description": "Cancel me",
                "quantity": 2,
                "unit_price_minor": 200,
            },
        ],
    )

    first_line_id = order.line_ids[0]
    second_line_id = order.line_ids[1]

    new_po = platform.reallocate_order_line(
        order_id=order.order_id,
        order_line_id=first_line_id,
        new_vendor_id="vendor_gamma",
        reason="vendor switch",
    )
    cancelled = platform.cancel_order_line(
        order_id=order.order_id,
        order_line_id=second_line_id,
        reason="customer changed mind",
    )

    assert new_po.vendor_id == "vendor_gamma"
    assert platform.store.order_lines[first_line_id].vendor_id == "vendor_gamma"
    assert cancelled.status == "cancelled"


def test_vendor_dispute_can_be_rejected() -> None:
    platform = _build_platform()
    order = platform.place_customer_order(
        tenant_id="tenant_demo",
        customer_id="cust_007",
        ship_to={"line1": "Reject St", "city": "London"},
        items=[{"vendor_id": "vendor_acme", "sku": "REJ-1", "description": "Reject", "quantity": 1, "unit_price_minor": 100}],
    )
    po_id = order.po_ids[0]
    po = platform.store.purchase_orders[po_id]
    po_line_id = po.line_ids[0]

    platform.vendor_acknowledge(
        po_id,
        [{"po_line_id": po_line_id, "accepted_quantity": 0, "status": "rejected", "reason": "no stock"}],
    )
    dispute_id = po.dispute_ids[0]
    result = platform.resolve_vendor_dispute(dispute_id, "rejected_vendor_terms")

    assert result.resolution == "rejected_vendor_terms"
    assert platform.store.purchase_orders[po_id].status == "rejected"
