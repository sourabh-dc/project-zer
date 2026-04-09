from __future__ import annotations

import os

from supply_v2.workers.maintenance_worker import MaintenanceWorker


def main() -> int:
    worker = MaintenanceWorker(os.environ["SUPPLY_V2_DB_URL"])
    result = worker.run_once()
    return result["notifications"] + result["slas"]


if __name__ == "__main__":
    raise SystemExit(main())
