from __future__ import annotations

import json
from uuid import uuid4
from datetime import datetime, timezone

from supply_v2.config import get_settings
from supply_v2.db import BrokerMessageRow, DeadLetterRow, build_session_factory


class DatabaseBroker:
    def __init__(self, engine) -> None:
        self.session_factory = build_session_factory(engine)

    def publish(self, topic: str, payload: dict) -> str:
        session = self.session_factory()
        try:
            message_id = f"broker_{uuid4().hex}"
            session.add(BrokerMessageRow(
                message_id=message_id,
                topic=topic,
                payload=json.dumps(payload),
                status="queued",
                available_at=datetime.now(timezone.utc),
                attempts=0,
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return message_id
        finally:
            session.close()


class AzureServiceBusBroker:
    def __init__(self, connection_string: str, queue_name: str) -> None:
        self.connection_string = connection_string
        self.queue_name = queue_name

    def publish(self, topic: str, payload: dict) -> str:
        try:
            from azure.servicebus import ServiceBusMessage
            from azure.servicebus import ServiceBusClient
        except ImportError as exc:
            raise RuntimeError("azure service bus sdk not installed") from exc

        message_id = f"broker_{uuid4().hex}"
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            sender = client.get_queue_sender(queue_name=self.queue_name)
            with sender:
                sender.send_messages(
                    ServiceBusMessage(
                        json.dumps({"topic": topic, "payload": payload}),
                        message_id=message_id,
                        application_properties={"topic": topic},
                    )
                )
        return message_id

    def dead_letter(self, message_id: str, topic: str, payload: str, reason: str) -> None:
        return None


def get_broker(engine=None):
    settings = get_settings()
    if settings.broker_backend == "azure_service_bus":
        if not settings.azure_service_bus_connection_string:
            raise RuntimeError("missing azure service bus settings")
        return AzureServiceBusBroker(
            connection_string=settings.azure_service_bus_connection_string,
            queue_name=settings.azure_service_bus_queue_name,
        )
    if engine is None:
        raise RuntimeError("database broker needs engine")
    return DatabaseBroker(engine)

    def dead_letter(self, message_id: str, topic: str, payload: str, reason: str) -> None:
        session = self.session_factory()
        try:
            session.add(DeadLetterRow(
                dead_letter_id=f"dead_{uuid4().hex}",
                message_id=message_id,
                topic=topic,
                payload=payload,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        finally:
            session.close()
