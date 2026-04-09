from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from supply_v2.apps.factory import create_combined_app
from supply_v2.persistent import PersistentPlatform
from supply_v2.workers.outbox_worker import NotificationWorker


def main() -> None:
    db_path = Path("/tmp/supply_v2_azure_live.sqlite")
    if db_path.exists():
        db_path.unlink()

    persistent = PersistentPlatform(database_url=f"sqlite+pysqlite:///{db_path}")
    app = create_combined_app(persistent=persistent)
    client = TestClient(app)

    vendor_id = "vendor_live_email"
    client.post(
        "/vendors",
        json={"vendor_id": vendor_id, "name": "Vendor Live", "primary_email": os.environ["AZURE_EMAIL_TO"]},
    )
    client.post(
        "/orders",
        json={
            "customer_id": "cust_live",
            "ship_to": {"line1": "Azure Live Street", "city": "London"},
            "items": [{"vendor_id": vendor_id, "sku": "LIVE-1", "description": "Live Check", "quantity": 1, "unit_price_minor": 100}],
        },
    )

    worker = NotificationWorker(persistent.engine)
    processed = worker.process_pending_notifications()
    print({"processed": processed})


if __name__ == "__main__":
    main()
