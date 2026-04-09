from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from supply_v2.apps.factory import create_combined_app
from supply_v2.persistent import PersistentPlatform


async def create_order(client: httpx.AsyncClient, idx: int) -> int:
    vendor_id = f"vendor_load_{idx % 3}"
    response = await client.post(
        "/orders",
        headers={"x-tenant-id": "tenant_load", "x-user-id": f"cust_{idx}", "x-role": "customer"},
        json={
            "customer_id": f"cust_{idx}",
            "ship_to": {"line1": "Load Street", "city": "London"},
            "items": [{"vendor_id": vendor_id, "sku": f"SKU-{idx}", "description": "Load", "quantity": 1, "unit_price_minor": 100}],
        },
    )
    response.raise_for_status()
    return response.status_code


async def main() -> None:
    db_path = Path("/tmp/supply_v2_load.sqlite")
    if db_path.exists():
        db_path.unlink()

    persistent = PersistentPlatform(database_url=f"sqlite+pysqlite:///{db_path}")
    app = create_combined_app(persistent=persistent)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for vendor_id in ["vendor_load_0", "vendor_load_1", "vendor_load_2"]:
            response = await client.post(
                "/vendors",
                headers={"x-tenant-id": "tenant_load", "x-user-id": "admin_load", "x-role": "admin"},
                json={"vendor_id": vendor_id, "name": vendor_id, "primary_email": f"{vendor_id}@test.com"},
            )
            response.raise_for_status()

        start = time.perf_counter()
        results = await asyncio.gather(*[create_order(client, idx) for idx in range(100)])
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        print({"requests": len(results), "elapsed_ms": elapsed_ms, "ok": all(code == 200 for code in results)})


if __name__ == "__main__":
    asyncio.run(main())
