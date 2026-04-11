from __future__ import annotations

import os

from supply_v2.db import build_engine
from supply_v2.workers.outbox_worker import NotificationWorker


def main() -> int:
    engine = build_engine(os.environ.get("SUPPLY_V2_DB_URL"))
    worker = NotificationWorker(engine)
    return worker.process_pending_notifications()


if __name__ == "__main__":
    raise SystemExit(main())
