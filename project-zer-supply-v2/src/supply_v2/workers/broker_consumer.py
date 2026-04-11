from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from supply_v2.config import get_settings
from supply_v2.db import BrokerMessageRow, EmailDeliveryRow, NotificationRow, build_session_factory
from supply_v2.email_provider import get_email_provider
from supply_v2.messaging.broker import DatabaseBroker


class BrokerConsumer:
    def __init__(self, engine, provider=None) -> None:
        self.session_factory = build_session_factory(engine)
        self.provider = provider or get_email_provider()
        self.broker = DatabaseBroker(engine)
        self.delivery_counter = 0
        self.settings = get_settings()

    def process_notifications(self) -> int:
        if self.settings.broker_backend != "database":
            return self._process_azure_notifications()
        session = self.session_factory()
        processed = 0
        try:
            now = datetime.now(timezone.utc)
            rows = session.query(BrokerMessageRow).filter(
                BrokerMessageRow.status == "queued",
                BrokerMessageRow.available_at <= now,
            ).all()
            for row in rows:
                row.attempts += 1
                payload = json.loads(row.payload)
                notification = session.query(NotificationRow).filter(
                    NotificationRow.notification_id == payload["notification_id"]
                ).first()
                if not notification:
                    row.status = "dead_lettered"
                    self.broker.dead_letter(row.message_id, row.topic, row.payload, "notification_not_found")
                    continue
                try:
                    result = self.provider.send(
                        to_email=notification.target_email,
                        subject=f"Purchase Order {notification.po_id}",
                        body=notification.payload,
                    )
                    notification.status = "sent"
                    row.status = "processed"
                    self.delivery_counter += 1
                    session.add(EmailDeliveryRow(
                        delivery_id=f"delivery_{self.delivery_counter:06d}",
                        notification_id=notification.notification_id,
                        provider=result.provider,
                        status=result.status,
                        external_message_id=result.message_id,
                        created_at=datetime.now(timezone.utc),
                    ))
                    processed += 1
                except Exception as exc:
                    if row.attempts >= 3:
                        row.status = "dead_lettered"
                        self.broker.dead_letter(row.message_id, row.topic, row.payload, str(exc))
                    else:
                        row.available_at = datetime.now(timezone.utc) + timedelta(seconds=2 ** row.attempts)
            session.commit()
            return processed
        finally:
            session.close()

    def _process_azure_notifications(self) -> int:
        try:
            from azure.servicebus import ServiceBusClient
        except ImportError as exc:
            raise RuntimeError("azure service bus sdk not installed") from exc

        processed = 0
        with ServiceBusClient.from_connection_string(self.settings.azure_service_bus_connection_string) as client:
            receiver = client.get_queue_receiver(queue_name=self.settings.azure_service_bus_queue_name, max_wait_time=5)
            with receiver:
                messages = receiver.receive_messages(max_message_count=10, max_wait_time=5)
                for message in messages:
                    try:
                        processed += self._handle_azure_message(message)
                        receiver.complete_message(message)
                    except Exception as exc:
                        receiver.dead_letter_message(message, reason=str(exc))
        return processed

    def _handle_azure_message(self, message) -> int:
        session = self.session_factory()
        try:
            raw_body = b"".join(bytes(part) for part in message.body).decode("utf-8")
            envelope = json.loads(raw_body)
            payload = envelope.get("payload", {})
            target_email = payload.get("target_email")
            if not target_email:
                raise RuntimeError("missing target_email")

            result = self.provider.send(
                to_email=target_email,
                subject=f"Purchase Order {payload.get('po_id', 'supply-v2')}",
                body=json.dumps(payload, sort_keys=True),
            )
            notification_id = payload.get("notification_id")
            if notification_id:
                notification = session.query(NotificationRow).filter(
                    NotificationRow.notification_id == notification_id
                ).first()
                if notification:
                    notification.status = "sent"
            self.delivery_counter += 1
            session.add(
                EmailDeliveryRow(
                    delivery_id=f"delivery_{uuid4().hex}",
                    notification_id=notification_id or f"external_{uuid4().hex}",
                    provider=result.provider,
                    status=result.status,
                    external_message_id=result.message_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return 1
        finally:
            session.close()
