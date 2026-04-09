from __future__ import annotations

import os

import uvicorn


def main() -> None:
    app_target = os.environ.get("SUPPLY_V2_APP_TARGET", "combined")
    port = int(os.environ.get("PORT", "8010"))
    mapping = {
        "combined": "supply_v2.api:app",
        "order": "supply_v2.apps.order_server:app",
        "procurement": "supply_v2.apps.procurement_server:app",
        "vendor": "supply_v2.apps.vendor_server:app",
        "fulfilment": "supply_v2.apps.fulfilment_server:app",
        "dispute": "supply_v2.apps.dispute_server:app",
        "invoice": "supply_v2.apps.invoice_server:app",
        "ops": "supply_v2.apps.ops_server:app",
    }
    uvicorn.run(mapping[app_target], host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
