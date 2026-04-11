from __future__ import annotations

from supply_v2.db import build_engine
from supply_v2.workers.outbox_worker import NotificationWorker
from supply_v2.workers.sla_worker import SLAWorker


class MaintenanceWorker:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def run_once(self) -> dict[str, int]:
        engine = build_engine(self.database_url)
        notifications = NotificationWorker(engine).process_pending_notifications()
        slas = SLAWorker(self.database_url).process_due_slas()
        return {"notifications": notifications, "slas": slas}
