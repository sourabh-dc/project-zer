from fastapi.testclient import TestClient

from supply_v2.api import create_app
from supply_v2.platform import SupplyPlatform


def _client() -> TestClient:
    app = create_app(SupplyPlatform())
    return TestClient(app)


def test_health_and_metrics_headers() -> None:
    client = _client()
    health = client.get("/health")
    metrics = client.get("/metrics")

    assert health.status_code == 200
    assert metrics.status_code == 200
    assert "x-request-id" in metrics.headers
    assert "x-response-time-ms" in metrics.headers


def test_http_end_to_end_flow() -> None:
    client = _client()

    for vendor in [
        {"vendor_id": "vendor_acme", "name": "Acme Supplies", "primary_email": "ops@acme.test"},
        {"vendor_id": "vendor_beta", "name": "Beta Industrial", "primary_email": "sales@beta.test"},
    ]:
        response = client.post("/vendors", json=vendor)
        assert response.status_code == 200

    order_response = client.post(
        "/orders",
        json={
            "customer_id": "cust_http",
            "ship_to": {"line1": "1 API Street", "city": "London"},
            "items": [
                {
                    "vendor_id": "vendor_acme",
                    "sku": "PAPER-001",
                    "description": "Paper",
                    "quantity": 10,
                    "unit_price_minor": 50,
                },
                {
                    "vendor_id": "vendor_beta",
                    "sku": "MUG-002",
                    "description": "Mug",
                    "quantity": 5,
                    "unit_price_minor": 300,
                },
            ],
        },
    )
    assert order_response.status_code == 200
    order = order_response.json()
    assert order["status"] == "fully_procured"
    assert len(order["po_ids"]) == 2
    vendor_listing = client.get("/vendors/vendor_acme/purchase-orders")
    assert vendor_listing.status_code == 200
    assert len(vendor_listing.json()["items"]) == 1

    acme_po_id = None
    beta_po_id = None
    for po_id in order["po_ids"]:
        po = client.get(f"/purchase-orders/{po_id}").json()
        if po["vendor_id"] == "vendor_acme":
            acme_po_id = po_id
            acme_line_id = po["lines"][0]["po_line_id"]
        else:
            beta_po_id = po_id
            beta_line_id = po["lines"][0]["po_line_id"]

    acme_ack = client.post(
        f"/purchase-orders/{acme_po_id}/acknowledge",
        json=[{"po_line_id": acme_line_id, "accepted_quantity": 10, "status": "accepted", "reason": ""}],
    )
    assert acme_ack.status_code == 200
    assert acme_ack.json()["status"] == "accepted"

    beta_ack = client.post(
        f"/purchase-orders/{beta_po_id}/acknowledge",
        json=[
            {
                "po_line_id": beta_line_id,
                "accepted_quantity": 4,
                "status": "quantity_changed",
                "reason": "one short",
            }
        ],
    )
    assert beta_ack.status_code == 200
    beta_po = beta_ack.json()
    assert beta_po["status"] == "accepted_with_changes"
    beta_dispute_id = beta_po["dispute_ids"][0]

    resolve_vendor = client.post(
        f"/disputes/{beta_dispute_id}/resolve",
        json={"resolution": "accepted_vendor_terms"},
    )
    assert resolve_vendor.status_code == 200
    assert resolve_vendor.json()["status"] == "resolved"

    acme_shipment = client.post(
        f"/purchase-orders/{acme_po_id}/shipments",
        json={"tracking_number": "TRACK-HTTP-1", "lines": [{"po_line_id": acme_line_id, "quantity": 10}]},
    )
    assert acme_shipment.status_code == 200

    beta_shipment = client.post(
        f"/purchase-orders/{beta_po_id}/shipments",
        json={"tracking_number": "TRACK-HTTP-2", "lines": [{"po_line_id": beta_line_id, "quantity": 4}]},
    )
    assert beta_shipment.status_code == 200

    receipt_ok = client.post(
        f"/orders/{order['order_id']}/receipts",
        json={
            "shipment_id": acme_shipment.json()["shipment_id"],
            "lines": [
                {
                    "shipment_line_id": acme_shipment.json()["lines"][0]["shipment_line_id"],
                    "received_quantity": 10,
                    "condition": "good",
                }
            ],
        },
    )
    assert receipt_ok.status_code == 200

    receipt_short = client.post(
        f"/orders/{order['order_id']}/receipts",
        json={
            "shipment_id": beta_shipment.json()["shipment_id"],
            "lines": [
                {
                    "shipment_line_id": beta_shipment.json()["lines"][0]["shipment_line_id"],
                    "received_quantity": 3,
                    "condition": "good",
                }
            ],
        },
    )
    assert receipt_short.status_code == 200

    order_after_receipts = client.get(f"/orders/{order['order_id']}").json()
    customer_dispute_id = next(
        dispute_id
        for dispute_id in order_after_receipts["dispute_ids"]
        if client.get(f"/disputes/{dispute_id}").json()["source"] == "customer"
    )

    resolve_customer = client.post(
        f"/disputes/{customer_dispute_id}/resolve",
        json={"resolution": "accept_customer_claim"},
    )
    assert resolve_customer.status_code == 200
    assert resolve_customer.json()["resolution"] == "accept_customer_claim"

    finalize = client.post(f"/orders/{order['order_id']}/finalize")
    assert finalize.status_code == 200
    assert finalize.json()["status"] == "completed"

    invoice_response = client.post(
        f"/purchase-orders/{acme_po_id}/invoices",
        json={
            "invoice_number": "INV-HTTP-1",
            "lines": [
                {
                    "po_line_id": acme_line_id,
                    "billed_quantity": 10,
                    "billed_unit_price_minor": 50,
                }
            ],
        },
        headers={"x-role": "vendor", "x-user-id": "vendor_acme"},
    )
    assert invoice_response.status_code == 200
    assert invoice_response.json()["status"] == "matched"

    sla_response = client.get(f"/purchase-orders/{acme_po_id}/slas")
    assert sla_response.status_code == 200
    assert len(sla_response.json()["items"]) == 1

    events = client.get("/events").json()["events"]
    assert len(events) >= 10


def test_admin_can_reallocate_and_cancel_line() -> None:
    client = _client()

    client.post("/vendors", json={"vendor_id": "vendor_a", "name": "Vendor A", "primary_email": "a@test.com"})
    client.post("/vendors", json={"vendor_id": "vendor_b", "name": "Vendor B", "primary_email": "b@test.com"})

    order = client.post(
        "/orders",
        json={
            "customer_id": "cust_ops",
            "ship_to": {"line1": "2 Ops Street", "city": "London"},
            "items": [
                {"vendor_id": "vendor_a", "sku": "SKU-A", "description": "A", "quantity": 1, "unit_price_minor": 100},
                {"vendor_id": "vendor_a", "sku": "SKU-B", "description": "B", "quantity": 1, "unit_price_minor": 100},
            ],
        },
    ).json()

    reallocate = client.post(
        f"/orders/{order['order_id']}/reallocate-line",
        json={"order_line_id": order["lines"][0]["order_line_id"], "new_vendor_id": "vendor_b", "reason": "rebalance"},
    )
    cancel = client.post(
        f"/orders/{order['order_id']}/cancel-line",
        json={"order_line_id": order["lines"][1]["order_line_id"], "reason": "cancelled"},
    )

    assert reallocate.status_code == 200
    assert reallocate.json()["vendor_id"] == "vendor_b"
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_idempotent_order_create_returns_same_response() -> None:
    client = _client()
    client.post("/vendors", json={"vendor_id": "vendor_idem", "name": "Vendor Idem", "primary_email": "idem@test.com"})

    payload = {
        "customer_id": "cust_idem",
        "ship_to": {"line1": "Idem Road", "city": "London"},
        "items": [{"vendor_id": "vendor_idem", "sku": "SKU-I", "description": "I", "quantity": 1, "unit_price_minor": 100}],
    }
    headers = {"x-idempotency-key": "idem-1"}
    first = client.post("/orders", json=payload, headers=headers)
    second = client.post("/orders", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["order_id"] == second.json()["order_id"]


def test_vendor_cannot_read_another_vendor_portal() -> None:
    client = _client()
    client.post("/vendors", json={"vendor_id": "vendor_one", "name": "Vendor One", "primary_email": "one@test.com"})
    client.post("/vendors", json={"vendor_id": "vendor_two", "name": "Vendor Two", "primary_email": "two@test.com"})

    response = client.get(
        "/vendors/vendor_two/purchase-orders",
        headers={"x-tenant-id": "tenant_demo", "x-user-id": "vendor_one", "x-role": "vendor"},
    )

    assert response.status_code == 403
    assert "vendor_scope_denied" in response.text


def test_customer_cannot_create_order_for_another_customer() -> None:
    client = _client()
    client.post("/vendors", json={"vendor_id": "vendor_scope", "name": "Vendor Scope", "primary_email": "scope@test.com"})

    response = client.post(
        "/orders",
        headers={"x-tenant-id": "tenant_demo", "x-user-id": "cust_real", "x-role": "customer"},
        json={
            "customer_id": "cust_other",
            "ship_to": {"line1": "Scope Road", "city": "London"},
            "items": [{"vendor_id": "vendor_scope", "sku": "SKU-S", "description": "Scoped", "quantity": 1, "unit_price_minor": 100}],
        },
    )

    assert response.status_code == 403
    assert "customer_scope_denied" in response.text


def test_vendor_cannot_ship_before_po_acceptance() -> None:
    client = _client()
    client.post("/vendors", json={"vendor_id": "vendor_ship", "name": "Vendor Ship", "primary_email": "ship@test.com"})
    order = client.post(
        "/orders",
        json={
            "customer_id": "cust_ship",
            "ship_to": {"line1": "Ship Road", "city": "London"},
            "items": [{"vendor_id": "vendor_ship", "sku": "SKU-SHIP", "description": "Ship", "quantity": 1, "unit_price_minor": 100}],
        },
    ).json()
    po_id = order["po_ids"][0]
    po = client.get(f"/purchase-orders/{po_id}").json()

    response = client.post(
        f"/purchase-orders/{po_id}/shipments",
        headers={"x-tenant-id": "tenant_demo", "x-user-id": "vendor_ship", "x-role": "vendor"},
        json={"tracking_number": "TRACK-SCOPE", "lines": [{"po_line_id": po["lines"][0]["po_line_id"], "quantity": 1}]},
    )

    assert response.status_code == 403
    assert "po_not_shippable" in response.text
