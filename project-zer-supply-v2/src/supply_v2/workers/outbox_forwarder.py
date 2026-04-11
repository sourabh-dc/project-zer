from __future__ import annotations

from supply_v2.config import get_settings
from supply_v2.db import OutboxEventRow, _loads, build_session_factory
from supply_v2.messaging.broker import get_broker


class OutboxForwarder:
    def __init__(self, engine) -> None:
        self.session_factory = build_session_factory(engine)
        self.broker = get_broker(engine)
        self.settings = get_settings()

    def forward_pending_events(self) -> int:
        session = self.session_factory()
        forwarded = 0
        try:
            rows = session.query(OutboxEventRow).filter(OutboxEventRow.status == "pending").all()
            for row in rows:
                self.broker.publish(topic=row.topic, payload=_loads(row.payload))
                row.status = "forwarded" if self.settings.broker_backend == "database" else "published"
                forwarded += 1
            session.commit()
            return forwarded
        finally:
            session.close()
