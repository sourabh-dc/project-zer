from __future__ import annotations

from supply_v2.models import Notification, OutboxEvent
from supply_v2.store import InMemoryStore
from supply_v2.vendor_access import issue_vendor_token


class NotificationService:
    def __init__(self, store: InMemoryStore, id_gen) -> None:
        self.store = store
        self.id_gen = id_gen

    def queue_vendor_po_email(self, tenant_id: str, vendor_id: str, po_id: str, target_email: str, payload: dict) -> Notification:
        vendor_token = issue_vendor_token(tenant_id=tenant_id, vendor_id=vendor_id, po_id=po_id)
        notification = Notification(
            notification_id=self.id_gen("notification"),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            po_id=po_id,
            target_email=target_email,
            template="vendor_po_email",
            payload={**payload, "vendor_token": vendor_token},
        )
        self.store.notifications[notification.notification_id] = notification
        outbox = OutboxEvent(
            outbox_id=self.id_gen("outbox"),
            tenant_id=tenant_id,
            topic="notification.send_email",
            aggregate_type="notification",
            aggregate_id=notification.notification_id,
            payload={
                "notification_id": notification.notification_id,
                "target_email": target_email,
                "template": notification.template,
                "po_id": po_id,
                "vendor_token": vendor_token,
            },
        )
        self.store.outbox_events[outbox.outbox_id] = outbox
        self.store.emit("vendor_notification.queued", notification.notification_id)
        return notification

    def send(self, notification_id: str) -> Notification:
        notification = self.store.notifications[notification_id]
        notification.status = "sent"
        self.store.emit("vendor_notification.sent", notification.notification_id)
        return notification
