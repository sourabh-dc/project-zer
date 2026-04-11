from __future__ import annotations

from supply_v2.persistent import PersistentPlatform


class SLAWorker:
    def __init__(self, database_url: str) -> None:
        self.persistent = PersistentPlatform(database_url=database_url)

    def process_due_slas(self) -> int:
        breached = self.persistent.platform.evaluate_slas()
        self.persistent.commit()
        return len(breached)
