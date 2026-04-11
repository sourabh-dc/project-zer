from __future__ import annotations

from procurement_service.Models import BrokerMessage, DeadLetter, EmailDelivery
from procurement_service.core.email_client import AzureCommunicationEmailSender


email_sender = AzureCommunicationEmailSender()


def _render_notification(notification) -> tuple[str, str, str]:
    payload = notification.payload or {}
    if notification.template == "vendor_po_email":
        po_number = payload.get("po_number", "")
        accept_url = payload.get("accept_url", "#")
        reject_url = payload.get("reject_url", "#")
        partial_url = payload.get("partial_url", "#")
        subject = f"Purchase Order {po_number} requires your response"
        plain_text = (
            f"Purchase Order {po_number} requires your action. "
            f"Accept: {accept_url} Reject: {reject_url} Partial: {partial_url}"
        )
        html = (
            f"<h3>Purchase Order {po_number}</h3>"
            "<p>Please respond using one of the actions below:</p>"
            f"<p><a href=\"{accept_url}\">Accept</a></p>"
            f"<p><a href=\"{reject_url}\">Reject</a></p>"
            f"<p><a href=\"{partial_url}\">Partially Accept</a></p>"
        )
        return subject, plain_text, html

    if notification.template == "customer_order_summary":
        items = payload.get("items", [])
        order_number = payload.get("order_number", "")
        total_minor = payload.get("order_total_minor", 0)
        currency = payload.get("currency", "USD")
        lines = [
            f"- {item.get('description', '')} ({item.get('sku', '')}) x{item.get('quantity', 0)}: {item.get('line_total_minor', 0)}"
            for item in items
        ]
        item_text = "\n".join(lines)
        subject = f"Order Confirmation {order_number}"
        plain_text = f"Order {order_number} confirmed. Total: {total_minor} {currency}.\n{item_text}"
        html_items = "".join([f"<li>{line}</li>" for line in lines])
        html = f"<h3>Order Confirmation {order_number}</h3><p>Total: {total_minor} {currency}</p><ul>{html_items}</ul>"
        return subject, plain_text, html

    subject = f"Notification {notification.notification_id}"
    plain_text = "You have a new notification from procurement service."
    html = "<p>You have a new notification from procurement service.</p>"
    return subject, plain_text, html


def dispatch_queued_notifications(container, *, order_id: str | None = None) -> int:
    processed = 0
    queued_notifications = [n for n in container.platform.store.notifications.values() if n.status == "queued"]

    for notification in queued_notifications:
        if order_id and notification.payload.get("order_id") != order_id:
            po_id = notification.po_id
            if po_id:
                po = container.platform.store.purchase_orders.get(po_id)
                if not po or po.order_id != order_id:
                    continue
            else:
                continue

        message = BrokerMessage(
            message_id=container.platform.id_gen("broker"),
            topic="notification.send_email",
            payload={
                "notification_id": notification.notification_id,
                "target_email": notification.target_email,
                "po_id": notification.po_id,
            },
            status="queued",
        )
        container.platform.store.broker_messages[message.message_id] = message

        if not notification.target_email or "@" not in notification.target_email:
            message.status = "dead_lettered"
            dead_letter = DeadLetter(
                dead_letter_id=container.platform.id_gen("dead"),
                message_id=message.message_id,
                topic=message.topic,
                payload=message.payload,
                reason="invalid target email",
            )
            container.platform.store.dead_letters[dead_letter.dead_letter_id] = dead_letter
            notification.status = "failed"
            container.platform.store.emit("notification.dead_lettered", dead_letter.dead_letter_id)
            continue

        subject, plain_text, html = _render_notification(notification)
        email_result = email_sender.send_email(
            to_email=notification.target_email,
            subject=subject,
            plain_text=plain_text,
            html=html,
        )

        if email_result.status in {"sent", "simulated"}:
            notification.status = "sent"
            message.status = "processed"
            processed += 1
        else:
            notification.status = "failed"
            message.status = "dead_lettered"
            dead_letter = DeadLetter(
                dead_letter_id=container.platform.id_gen("dead"),
                message_id=message.message_id,
                topic=message.topic,
                payload=message.payload,
                reason=email_result.reason or "email send failed",
            )
            container.platform.store.dead_letters[dead_letter.dead_letter_id] = dead_letter
            container.platform.store.emit("notification.dead_lettered", dead_letter.dead_letter_id)

        delivery = EmailDelivery(
            delivery_id=container.platform.id_gen("delivery"),
            notification_id=notification.notification_id,
            provider="azure_communication",
            status=email_result.status,
            external_message_id=email_result.external_message_id or message.message_id,
        )
        container.platform.store.email_deliveries[delivery.delivery_id] = delivery

        if notification.template == "vendor_po_email":
            container.platform.store.emit("vendor_notification.sent", notification.notification_id)
        if notification.template == "customer_order_summary":
            container.platform.store.emit("customer_notification.sent", notification.notification_id)

    return processed
