from fastapi.testclient import TestClient

from supply_v2.api import create_app
from supply_v2.platform import SupplyPlatform


def main() -> None:
    client = TestClient(create_app(SupplyPlatform()))

    client.post("/vendors", json={"vendor_id": "vendor_acme", "name": "Acme Supplies", "primary_email": "ops@acme.test"})
    client.post("/vendors", json={"vendor_id": "vendor_beta", "name": "Beta Industrial", "primary_email": "sales@beta.test"})

    order = client.post(
        "/orders",
        json={
            "customer_id": "cust_api_demo",
            "ship_to": {"line1": "77 API Road", "city": "London"},
            "items": [
                {"vendor_id": "vendor_acme", "sku": "PEN-1", "description": "Pen", "quantity": 10, "unit_price_minor": 100},
                {"vendor_id": "vendor_beta", "sku": "MUG-2", "description": "Mug", "quantity": 5, "unit_price_minor": 300},
            ],
        },
    ).json()

    po_a = client.get(f"/purchase-orders/{order['po_ids'][0]}").json()
    po_b = client.get(f"/purchase-orders/{order['po_ids'][1]}").json()
    if po_a["vendor_id"] != "vendor_acme":
        po_a, po_b = po_b, po_a

    client.post(
        f"/purchase-orders/{po_a['po_id']}/acknowledge",
        json=[{"po_line_id": po_a["lines"][0]["po_line_id"], "accepted_quantity": 10, "status": "accepted", "reason": ""}],
    )
    disputed = client.post(
        f"/purchase-orders/{po_b['po_id']}/acknowledge",
        json=[{"po_line_id": po_b["lines"][0]["po_line_id"], "accepted_quantity": 4, "status": "quantity_changed", "reason": "one short"}],
    ).json()

    vendor_dispute_id = disputed["dispute_ids"][0]
    client.post(f"/disputes/{vendor_dispute_id}/resolve", json={"resolution": "accepted_vendor_terms"})

    shipment_a = client.post(
        f"/purchase-orders/{po_a['po_id']}/shipments",
        json={"tracking_number": "TRACK-A", "lines": [{"po_line_id": po_a["lines"][0]["po_line_id"], "quantity": 10}]},
    ).json()
    shipment_b = client.post(
        f"/purchase-orders/{po_b['po_id']}/shipments",
        json={"tracking_number": "TRACK-B", "lines": [{"po_line_id": po_b["lines"][0]["po_line_id"], "quantity": 4}]},
    ).json()

    client.post(
        f"/orders/{order['order_id']}/receipts",
        json={"shipment_id": shipment_a["shipment_id"], "lines": [{"shipment_line_id": shipment_a["lines"][0]["shipment_line_id"], "received_quantity": 10, "condition": "good"}]},
    )
    client.post(
        f"/orders/{order['order_id']}/receipts",
        json={"shipment_id": shipment_b["shipment_id"], "lines": [{"shipment_line_id": shipment_b["lines"][0]["shipment_line_id"], "received_quantity": 3, "condition": "good"}]},
    )

    current_order = client.get(f"/orders/{order['order_id']}").json()
    customer_dispute_id = next(
        dispute_id
        for dispute_id in current_order["dispute_ids"]
        if client.get(f"/disputes/{dispute_id}").json()["source"] == "customer"
    )
    client.post(f"/disputes/{customer_dispute_id}/resolve", json={"resolution": "refund_issued"})
    final_order = client.post(f"/orders/{order['order_id']}/finalize").json()
    events = client.get("/events").json()["events"]

    print(f"order={final_order['order_number']} status={final_order['status']}")
    print(f"po_count={len(final_order['po_ids'])} dispute_count={len(final_order['dispute_ids'])} events={len(events)}")
    for po_id in final_order["po_ids"]:
        po = client.get(f"/purchase-orders/{po_id}").json()
        print(f"{po['po_number']} vendor={po['vendor_id']} status={po['status']}")


if __name__ == "__main__":
    main()
