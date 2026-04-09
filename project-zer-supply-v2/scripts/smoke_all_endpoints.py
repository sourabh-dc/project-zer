from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from supply_v2.apps.factory import create_combined_app
from supply_v2.persistent import PersistentPlatform


def main() -> None:
    db_path = Path("/tmp/supply_v2_smoke.sqlite")
    if db_path.exists():
        db_path.unlink()

    persistent = PersistentPlatform(database_url=f"sqlite+pysqlite:///{db_path}")
    client = TestClient(create_combined_app(persistent=persistent))

    headers_admin = {"x-tenant-id": "tenant_smoke", "x-user-id": "user_admin", "x-role": "admin"}
    headers_vendor = {"x-tenant-id": "tenant_smoke", "x-user-id": "user_vendor", "x-role": "vendor"}
    headers_customer = {"x-tenant-id": "tenant_smoke", "x-user-id": "user_customer", "x-role": "customer"}

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200

    for vendor in [
        {"vendor_id": "vendor_a", "name": "Vendor A", "primary_email": "a@test.com"},
        {"vendor_id": "vendor_b", "name": "Vendor B", "primary_email": "b@test.com"},
        {"vendor_id": "vendor_c", "name": "Vendor C", "primary_email": "c@test.com"},
    ]:
        assert client.post("/vendors", json=vendor, headers=headers_admin).status_code == 200

    order = client.post(
        "/orders",
        headers=headers_customer,
        json={
            "customer_id": "cust_smoke",
            "ship_to": {"line1": "Smoke Street", "city": "London"},
            "items": [
                {"vendor_id": "vendor_a", "sku": "SKU-A", "description": "A", "quantity": 3, "unit_price_minor": 100},
                {"vendor_id": "vendor_b", "sku": "SKU-B", "description": "B", "quantity": 2, "unit_price_minor": 200},
                {"vendor_id": "vendor_c", "sku": "SKU-C", "description": "C", "quantity": 1, "unit_price_minor": 300},
            ],
        },
    )
    assert order.status_code == 200
    order_body = order.json()
    order_id = order_body["order_id"]

    pos = [client.get(f"/purchase-orders/{po_id}", headers=headers_admin).json() for po_id in order_body["po_ids"]]
    po_by_vendor = {po["vendor_id"]: po for po in pos}

    assert client.get("/vendors/vendor_a/purchase-orders", headers=headers_admin).status_code == 200
    assert client.get("/vendors/vendor_a/shipments", headers=headers_admin).status_code == 200
    assert client.get("/vendors/vendor_a/disputes", headers=headers_admin).status_code == 200
    assert client.get(f"/orders/{order_id}", headers=headers_customer).status_code == 200

    assert client.post(
        f"/purchase-orders/{po_by_vendor['vendor_a']['po_id']}/acknowledge",
        headers=headers_vendor,
        json=[{"po_line_id": po_by_vendor["vendor_a"]["lines"][0]["po_line_id"], "accepted_quantity": 3, "status": "accepted"}],
    ).status_code == 200

    dispute_po = client.post(
        f"/purchase-orders/{po_by_vendor['vendor_b']['po_id']}/acknowledge",
        headers=headers_vendor,
        json=[{"po_line_id": po_by_vendor["vendor_b"]["lines"][0]["po_line_id"], "accepted_quantity": 1, "status": "quantity_changed", "reason": "partial"}],
    )
    assert dispute_po.status_code == 200
    dispute_id = dispute_po.json()["dispute_ids"][0]
    assert client.get(f"/disputes/{dispute_id}", headers=headers_admin).status_code == 200
    assert client.post(f"/disputes/{dispute_id}/resolve", headers=headers_admin, json={"resolution": "accepted_vendor_terms"}).status_code == 200

    reallocated = client.post(
        f"/orders/{order_id}/reallocate-line",
        headers=headers_admin,
        json={"order_line_id": order_body["lines"][2]["order_line_id"], "new_vendor_id": "vendor_a", "reason": "best cost"},
    )
    assert reallocated.status_code == 200

    shipment_a = client.post(
        f"/purchase-orders/{po_by_vendor['vendor_a']['po_id']}/shipments",
        headers=headers_vendor,
        json={"tracking_number": "TRACK-A", "lines": [{"po_line_id": po_by_vendor["vendor_a"]["lines"][0]["po_line_id"], "quantity": 3}]},
    )
    assert shipment_a.status_code == 200

    po_reallocated = reallocated.json()
    shipment_c = client.post(
        f"/purchase-orders/{po_reallocated['po_id']}/shipments",
        headers=headers_vendor,
        json={"tracking_number": "TRACK-C", "lines": [{"po_line_id": po_reallocated["lines"][0]["po_line_id"], "quantity": 1}]},
    )
    assert shipment_c.status_code == 200

    po_b = client.get(f"/purchase-orders/{po_by_vendor['vendor_b']['po_id']}", headers=headers_admin).json()
    shipment_b = client.post(
        f"/purchase-orders/{po_b['po_id']}/shipments",
        headers=headers_vendor,
        json={"tracking_number": "TRACK-B", "lines": [{"po_line_id": po_b["lines"][0]["po_line_id"], "quantity": 1}]},
    )
    assert shipment_b.status_code == 200

    for shipment, qty in [(shipment_a.json(), 3), (shipment_b.json(), 1), (shipment_c.json(), 1)]:
        assert client.post(
            f"/orders/{order_id}/receipts",
            headers=headers_customer,
            json={
                "shipment_id": shipment["shipment_id"],
                "lines": [{"shipment_line_id": shipment["lines"][0]["shipment_line_id"], "received_quantity": qty, "condition": "good"}],
            },
        ).status_code == 200

    assert client.post(
        f"/purchase-orders/{po_by_vendor['vendor_a']['po_id']}/invoices",
        headers=headers_vendor,
        json={
            "invoice_number": "INV-SMOKE-1",
            "lines": [{"po_line_id": po_by_vendor["vendor_a"]["lines"][0]["po_line_id"], "billed_quantity": 3, "billed_unit_price_minor": 100}],
        },
    ).status_code == 200

    assert client.get(f"/purchase-orders/{po_by_vendor['vendor_a']['po_id']}/slas", headers=headers_admin).status_code == 200
    assert client.post("/ops/run-notifications", headers=headers_admin).status_code == 200
    assert client.post("/ops/run-slas", headers=headers_admin).status_code == 200
    assert client.get("/ops/dead-letters", headers=headers_admin).status_code == 200
    assert client.post(f"/orders/{order_id}/finalize", headers=headers_admin).status_code == 200
    assert client.get("/events").status_code == 200

    print(json.dumps({"status": "ok", "order_id": order_id}, indent=2))


if __name__ == "__main__":
    main()
