from __future__ import annotations

import os
import time

from supply_v2.workers.maintenance_worker import MaintenanceWorker


def main() -> int:
    interval_seconds = int(os.environ.get("SUPPLY_V2_SCHEDULER_INTERVAL_SECONDS", "30"))
    worker = MaintenanceWorker(os.environ["SUPPLY_V2_DB_URL"])
    while True:
        worker.run_once()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
