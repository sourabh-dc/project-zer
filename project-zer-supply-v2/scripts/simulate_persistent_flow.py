from pathlib import Path
import os

from fastapi.testclient import TestClient

from supply_v2.api import create_app
from supply_v2.persistent import PersistentPlatform


def main() -> None:
    database_url = os.getenv("SUPPLY_V2_DB_URL")
    db_path = Path("runtime_demo.sqlite").resolve()
    if not database_url:
        database_url = f"sqlite+pysqlite:///{db_path}"

    persistent = PersistentPlatform(database_url=database_url, snapshot_key="demo")
    client = TestClient(create_app(persistent=persistent))

    client.post("/vendors", json={"vendor_id": "vendor_acme", "name": "Acme Supplies", "primary_email": "ops@acme.test"})
    order = client.post(
        "/orders",
        json={
            "customer_id": "cust_db_demo",
            "ship_to": {"line1": "99 DB Lane", "city": "London"},
            "items": [
                {"vendor_id": "vendor_acme", "sku": "PAPER-DB", "description": "Paper", "quantity": 3, "unit_price_minor": 200}
            ],
        },
    ).json()

    po = client.get(f"/purchase-orders/{order['po_ids'][0]}").json()
    client.post(
        f"/purchase-orders/{po['po_id']}/acknowledge",
        json=[{"po_line_id": po["lines"][0]["po_line_id"], "accepted_quantity": 3, "status": "accepted", "reason": ""}],
    )
    shipment = client.post(
        f"/purchase-orders/{po['po_id']}/shipments",
        json={"tracking_number": "TRACK-DB", "lines": [{"po_line_id": po["lines"][0]["po_line_id"], "quantity": 3}]},
    ).json()
    client.post(
        f"/orders/{order['order_id']}/receipts",
        json={"shipment_id": shipment["shipment_id"], "lines": [{"shipment_line_id": shipment["lines"][0]["shipment_line_id"], "received_quantity": 3, "condition": "good"}]},
    )
    final_order = client.post(f"/orders/{order['order_id']}/finalize").json()

    reloaded = PersistentPlatform(database_url=database_url, snapshot_key="demo")
    reloaded_client = TestClient(create_app(persistent=reloaded))
    persisted_order = reloaded_client.get(f"/orders/{order['order_id']}").json()

    print(f"db_target={database_url}")
    print(f"order={final_order['order_number']} status={final_order['status']}")
    print(f"reloaded_status={persisted_order['status']} po_count={len(persisted_order['po_ids'])}")


if __name__ == "__main__":
    main()
