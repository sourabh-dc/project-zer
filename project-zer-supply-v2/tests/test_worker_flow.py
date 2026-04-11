from fastapi.testclient import TestClient

from supply_v2.apps.factory import create_combined_app, create_order_app, create_procurement_app, create_vendor_app
from supply_v2.db import BrokerMessageRow, EmailDeliveryRow, OutboxEventRow
from supply_v2.persistent import PersistentPlatform
from supply_v2.workers.outbox_worker import NotificationWorker


def test_split_apps_share_same_platform() -> None:
    persistent = PersistentPlatform(database_url="sqlite+pysqlite:///:memory:")
    vendor_client = TestClient(create_vendor_app(persistent=persistent))
    order_client = TestClient(create_order_app(persistent=persistent))
    procurement_client = TestClient(create_procurement_app(persistent=persistent))

    vendor_client.post("/vendors", json={"vendor_id": "vendor_split", "name": "Split Vendor", "primary_email": "split@test.com"})
    order_resp = order_client.post(
        "/orders",
        json={
            "customer_id": "cust_split",
            "ship_to": {"line1": "Split St", "city": "London"},
            "items": [{"vendor_id": "vendor_split", "sku": "SKU-S", "description": "Split", "quantity": 1, "unit_price_minor": 900}],
        },
    )
    po_id = order_resp.json()["po_ids"][0]
    po_resp = procurement_client.get(f"/purchase-orders/{po_id}")

    assert order_resp.status_code == 200
    assert po_resp.status_code == 200
    assert po_resp.json()["vendor_id"] == "vendor_split"


def test_notification_worker_sends_queued_notifications(tmp_path) -> None:
    db_path = tmp_path / "worker.sqlite"
    persistent = PersistentPlatform(database_url=f"sqlite+pysqlite:///{db_path}")
    client = TestClient(create_combined_app(persistent=persistent))

    client.post("/vendors", json={"vendor_id": "vendor_worker", "name": "Worker Vendor", "primary_email": "worker@test.com"})
    client.post(
        "/orders",
        json={
            "customer_id": "cust_worker",
            "ship_to": {"line1": "Worker St", "city": "London"},
            "items": [{"vendor_id": "vendor_worker", "sku": "SKU-W", "description": "Worker", "quantity": 1, "unit_price_minor": 700}],
        },
    )

    worker = NotificationWorker(persistent.engine)
    processed = worker.process_pending_notifications()

    session = persistent.session_factory()
    try:
        deliveries = session.query(EmailDeliveryRow).count()
        outbox_forwarded = session.query(OutboxEventRow).filter(OutboxEventRow.status == "forwarded").count()
        broker_processed = session.query(BrokerMessageRow).filter(BrokerMessageRow.status == "processed").count()
    finally:
        session.close()

    assert processed == 1
    assert deliveries == 1
    assert outbox_forwarded == 1
    assert broker_processed == 1


def test_tenant_scoping_blocks_cross_tenant_reads() -> None:
    persistent = PersistentPlatform(database_url="sqlite+pysqlite:///:memory:")
    client = TestClient(create_combined_app(persistent=persistent))

    headers_a = {"x-tenant-id": "tenant_a", "x-user-id": "user_a"}
    headers_b = {"x-tenant-id": "tenant_b", "x-user-id": "user_b"}

    client.post("/vendors", json={"vendor_id": "vendor_a", "name": "Vendor A", "primary_email": "a@test.com"}, headers=headers_a)
    order_resp = client.post(
        "/orders",
        json={
            "customer_id": "cust_a",
            "ship_to": {"line1": "Tenant A", "city": "London"},
            "items": [{"vendor_id": "vendor_a", "sku": "SKU-A", "description": "Tenant A Item", "quantity": 1, "unit_price_minor": 500}],
        },
        headers=headers_a,
    )
    order_id = order_resp.json()["order_id"]

    ok_resp = client.get(f"/orders/{order_id}", headers=headers_a)
    blocked_resp = client.get(f"/orders/{order_id}", headers=headers_b)

    assert ok_resp.status_code == 200
    assert blocked_resp.status_code == 403


def test_role_guard_blocks_vendor_master_write() -> None:
    persistent = PersistentPlatform(database_url="sqlite+pysqlite:///:memory:")
    client = TestClient(create_combined_app(persistent=persistent))

    response = client.post(
        "/vendors",
        json={"vendor_id": "vendor_denied", "name": "Denied", "primary_email": "deny@test.com"},
        headers={"x-tenant-id": "tenant_a", "x-user-id": "user_a", "x-role": "vendor"},
    )

    assert response.status_code == 403


def test_ops_endpoint_runs_notification_worker() -> None:
    persistent = PersistentPlatform(database_url="sqlite+pysqlite:///:memory:")
    client = TestClient(create_combined_app(persistent=persistent))

    client.post("/vendors", json={"vendor_id": "vendor_ops", "name": "Ops Vendor", "primary_email": "ops@test.com"})
    client.post(
        "/orders",
        json={
            "customer_id": "cust_ops",
            "ship_to": {"line1": "Ops Street", "city": "London"},
            "items": [{"vendor_id": "vendor_ops", "sku": "SKU-O", "description": "Ops", "quantity": 1, "unit_price_minor": 700}],
        },
    )

    response = client.post("/ops/run-notifications")

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    assert client.get("/ops/audit-events").status_code == 200
    assert client.get("/ops/rbac/roles").status_code == 200
    assert client.get("/ops/rbac/permissions").status_code == 200
    assert client.post("/internal/maintenance/run", headers={"x-internal-api-key": "local-internal-key"}).status_code == 200
