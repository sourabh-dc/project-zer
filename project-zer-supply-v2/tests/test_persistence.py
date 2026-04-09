from fastapi.testclient import TestClient

from supply_v2.api import create_app
from supply_v2.db import InvoiceRow, OrderLineRow, OrderRow, PurchaseOrderRow, SLARecordRow, VendorRow
from supply_v2.persistent import PersistentPlatform


def test_persistent_platform_survives_reload(tmp_path) -> None:
    db_path = tmp_path / "supply_v2.sqlite"
    database_url = f"sqlite+pysqlite:///{db_path}"

    persistent_a = PersistentPlatform(database_url=database_url, snapshot_key="test")
    client_a = TestClient(create_app(persistent=persistent_a))

    client_a.post("/vendors", json={"vendor_id": "vendor_one", "name": "Vendor One", "primary_email": "one@test.com"})
    order_resp = client_a.post(
        "/orders",
        json={
            "customer_id": "cust_persist",
            "ship_to": {"line1": "Persist Lane", "city": "London"},
            "items": [
                {
                    "vendor_id": "vendor_one",
                    "sku": "SKU-1",
                    "description": "Persistent Item",
                    "quantity": 2,
                    "unit_price_minor": 700,
                }
            ],
        },
    )
    assert order_resp.status_code == 200
    order_id = order_resp.json()["order_id"]
    po_id = order_resp.json()["po_ids"][0]
    po_line_id = client_a.get(f"/purchase-orders/{po_id}").json()["lines"][0]["po_line_id"]
    ack_resp = client_a.post(
        f"/purchase-orders/{po_id}/acknowledge",
        json=[{"po_line_id": po_line_id, "accepted_quantity": 2, "status": "accepted", "reason": ""}],
    )
    assert ack_resp.status_code == 200
    invoice_resp = client_a.post(
        f"/purchase-orders/{po_id}/invoices",
        json={
            "invoice_number": "INV-PERSIST-1",
            "lines": [{"po_line_id": po_line_id, "billed_quantity": 2, "billed_unit_price_minor": 700}],
        },
        headers={"x-role": "vendor", "x-user-id": "vendor_one"},
    )
    assert invoice_resp.status_code == 200

    persistent_b = PersistentPlatform(database_url=database_url, snapshot_key="test")
    client_b = TestClient(create_app(persistent=persistent_b))

    order_after = client_b.get(f"/orders/{order_id}")
    po_after = client_b.get(f"/purchase-orders/{po_id}")

    assert order_after.status_code == 200
    assert po_after.status_code == 200
    assert order_after.json()["customer_id"] == "cust_persist"
    assert po_after.json()["vendor_id"] == "vendor_one"
    assert client_b.get(f"/purchase-orders/{po_id}/slas").status_code == 200

    session = persistent_b.session_factory()
    try:
        assert session.query(VendorRow).count() == 1
        assert session.query(OrderRow).count() == 1
        assert session.query(OrderLineRow).count() == 1
        assert session.query(PurchaseOrderRow).count() == 1
        assert session.query(InvoiceRow).count() == 1
        assert session.query(SLARecordRow).count() == 1
    finally:
        session.close()
