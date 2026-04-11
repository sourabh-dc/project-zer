from __future__ import annotations

from supply_v2.email_provider import get_email_provider
from supply_v2.workers.broker_consumer import BrokerConsumer
from supply_v2.workers.outbox_forwarder import OutboxForwarder


class NotificationWorker:
    def __init__(self, engine, provider=None) -> None:
        self.forwarder = OutboxForwarder(engine)
        self.consumer = BrokerConsumer(engine, provider=provider or get_email_provider())

    def process_pending_notifications(self) -> int:
        self.forwarder.forward_pending_events()
        return self.consumer.process_notifications()
