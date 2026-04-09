from __future__ import annotations

import os

from supply_v2.workers.sla_worker import SLAWorker


def main() -> int:
    worker = SLAWorker(os.environ["SUPPLY_V2_DB_URL"])
    return worker.process_due_slas()


if __name__ == "__main__":
    raise SystemExit(main())
