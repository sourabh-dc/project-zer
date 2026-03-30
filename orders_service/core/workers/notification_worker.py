import json
import uuid
import asyncio
import logging
import os
from datetime import datetime, timezone

from orders_service.Models import OutboxEvent, OutboxEventDelivery, PurchaseRequest, Vendor, User
from orders_service.core.db_config import SessionLocal

logger = logging.getLogger("notification_worker")

environment = os.getenv("ENVIRONMENT", "local").lower()


def _decode_message_body(msg):
    try:
        body_bytes = b""
        if hasattr(msg, "body"):
            for part in msg.body:
                if isinstance(part, (bytes, bytearray)):
                    body_bytes += bytes(part)
                else:
                    body_bytes += str(part).encode("utf-8")
        else:
            body_bytes = str(msg).encode("utf-8")
        return json.loads(body_bytes.decode("utf-8"))
    except Exception as exc:
        logger.error(f"Failed to decode message body: {exc}")
        return None


def _build_vendor_email_html(
    vendor_name: str,
    requester_name: str,
    reference_number: str,
    description: str,
    amount_display: str,
    currency: str,
    line_items: list | None,
    accept_url: str,
    reject_url: str,
) -> str:
    items_html = ""
    if line_items:
        rows = ""
        for item in line_items:
            desc = item.get("description", item.get("product_id", "—"))
            qty = item.get("qty", item.get("quantity", "—"))
            price = item.get("unit_price_minor", 0)
            price_display = f"{currency} {price / 100:,.2f}" if isinstance(price, (int, float)) else str(price)
            rows += f"""
                <tr>
                    <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb;">{desc}</td>
                    <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; text-align:center;">{qty}</td>
                    <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb; text-align:right;">{price_display}</td>
                </tr>"""
        items_html = f"""
            <table style="width:100%; border-collapse:collapse; margin:16px 0;">
                <thead>
                    <tr style="background:#f9fafb;">
                        <th style="padding:8px 12px; text-align:left; border-bottom:2px solid #e5e7eb;">Item</th>
                        <th style="padding:8px 12px; text-align:center; border-bottom:2px solid #e5e7eb;">Qty</th>
                        <th style="padding:8px 12px; text-align:right; border-bottom:2px solid #e5e7eb;">Unit Price</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0; padding:0; background:#f5f7fa; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f7fa; padding:32px 0;">
            <tr><td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 4px 24px rgba(0,0,0,0.06);">
                    <!-- Header -->
                    <tr>
                        <td style="background:#1a1a2e; padding:28px 32px;">
                            <h1 style="margin:0; color:#ffffff; font-size:20px; font-weight:600;">
                                New Purchase Request
                            </h1>
                        </td>
                    </tr>
                    <!-- Body -->
                    <tr>
                        <td style="padding:32px;">
                            <p style="margin:0 0 16px; color:#374151; font-size:15px; line-height:1.6;">
                                Dear <strong>{vendor_name}</strong>,
                            </p>
                            <p style="margin:0 0 24px; color:#374151; font-size:15px; line-height:1.6;">
                                A new purchase request has been submitted by <strong>{requester_name}</strong>
                                and requires your response.
                            </p>

                            <!-- Order Details Card -->
                            <div style="background:#f9fafb; border-radius:8px; padding:20px; margin-bottom:24px;">
                                <table style="width:100%;">
                                    <tr>
                                        <td style="padding:4px 0; color:#6b7280; font-size:13px;">Reference</td>
                                        <td style="padding:4px 0; color:#1a1a2e; font-size:13px; font-weight:600; text-align:right;">{reference_number}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding:4px 0; color:#6b7280; font-size:13px;">Description</td>
                                        <td style="padding:4px 0; color:#1a1a2e; font-size:13px; text-align:right;">{description or '—'}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding:4px 0; color:#6b7280; font-size:13px;">Total Amount</td>
                                        <td style="padding:4px 0; color:#1a1a2e; font-size:16px; font-weight:700; text-align:right;">{currency} {amount_display}</td>
                                    </tr>
                                </table>
                            </div>

                            {items_html}

                            <p style="margin:0 0 24px; color:#374151; font-size:15px; line-height:1.6;">
                                Please review the details above and accept or reject this purchase request:
                            </p>

                            <!-- Action Buttons -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="padding:0 8px 0 0;" width="50%">
                                        <a href="{accept_url}"
                                           style="display:block; padding:14px 24px; background:#059669; color:#ffffff;
                                                  text-decoration:none; border-radius:8px; font-size:15px;
                                                  font-weight:600; text-align:center;">
                                            Accept Order
                                        </a>
                                    </td>
                                    <td align="center" style="padding:0 0 0 8px;" width="50%">
                                        <a href="{reject_url}"
                                           style="display:block; padding:14px 24px; background:#dc2626; color:#ffffff;
                                                  text-decoration:none; border-radius:8px; font-size:15px;
                                                  font-weight:600; text-align:center;">
                                            Reject Order
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="background:#f9fafb; padding:20px 32px; border-top:1px solid #e5e7eb;">
                            <p style="margin:0; color:#9ca3af; font-size:12px; text-align:center;">
                                This is an automated message from ZeroQue. Please do not reply to this email.
                            </p>
                        </td>
                    </tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>"""


def _send_vendor_email(
    to_email: str,
    vendor_name: str,
    requester_name: str,
    reference_number: str,
    description: str,
    amount_minor: int,
    currency: str,
    line_items: list | None,
    accept_url: str,
    reject_url: str,
):
    from azure.communication.email import EmailClient
    from orders_service.core.config import SETTINGS

    amount_display = f"{amount_minor / 100:,.2f}"

    html_content = _build_vendor_email_html(
        vendor_name=vendor_name,
        requester_name=requester_name,
        reference_number=reference_number,
        description=description,
        amount_display=amount_display,
        currency=currency,
        line_items=line_items,
        accept_url=accept_url,
        reject_url=reject_url,
    )

    plain_text = (
        f"Dear {vendor_name},\n\n"
        f"A new purchase request ({reference_number}) has been submitted by {requester_name}.\n"
        f"Amount: {currency} {amount_display}\n"
        f"Description: {description or '—'}\n\n"
        f"Accept: {accept_url}\n"
        f"Reject: {reject_url}\n\n"
        f"Please click one of the links above to respond.\n"
    )

    client = EmailClient.from_connection_string(SETTINGS.EMAIL_CONNECTION_STRING)
    message = {
        "senderAddress": SETTINGS.EMAIL_SENDER_ADDRESS,
        "recipients": {"to": [{"address": to_email, "displayName": vendor_name}]},
        "content": {
            "subject": f"Purchase Request {reference_number} — Action Required",
            "plainText": plain_text,
            "html": html_content,
        },
    }

    poller = client.begin_send(message)
    result = poller.result()
    logger.info(f"Vendor email sent to {to_email} for {reference_number}, message_id={result.get('id', 'n/a') if isinstance(result, dict) else result}")
    return result


def _handle_vendor_notification(db, event: OutboxEvent):
    from orders_service.core.config import SETTINGS

    payload = event.payload
    request_id = payload.get("request_id")

    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.request_id == uuid.UUID(request_id)
    ).first()
    if not pr:
        raise ValueError(f"PurchaseRequest {request_id} not found")

    if not pr.vendor_id:
        logger.info(f"No vendor on request {request_id}, skipping email")
        return

    vendor = db.query(Vendor).filter(Vendor.vendor_id == pr.vendor_id).first()
    if not vendor or not vendor.contact_email:
        logger.warning(f"Vendor {pr.vendor_id} not found or has no contact_email, skipping")
        return

    requester = db.query(User).filter(User.user_id == pr.requester_id).first()
    requester_name = f"{requester.first_name} {requester.last_name}" if requester else "Unknown"

    base_url = SETTINGS.ORDERS_BASE_URL.rstrip("/")
    accept_url = f"{base_url}/vendor-action/{pr.vendor_action_token}/accept"
    reject_url = f"{base_url}/vendor-action/{pr.vendor_action_token}/reject"

    _send_vendor_email(
        to_email=vendor.contact_email,
        vendor_name=vendor.name or "Vendor",
        requester_name=requester_name,
        reference_number=pr.reference_number or str(pr.request_id),
        description=pr.description,
        amount_minor=pr.amount_minor,
        currency=pr.currency,
        line_items=pr.line_items,
        accept_url=accept_url,
        reject_url=reject_url,
    )


async def process_notifications():
    """Listen to service bus queue and process vendor notification events."""
    if environment == "local":
        logger.info("Notification worker disabled in local environment, using polling fallback")
        await _poll_fallback()
        return

    from azure.identity.aio import DefaultAzureCredential
    from azure.servicebus.aio import ServiceBusClient
    from orders_service.core.config import SETTINGS

    cred = DefaultAzureCredential()
    client = ServiceBusClient(SETTINGS.SB_NAMESPACE, cred)

    async with client:
        receiver = client.get_queue_receiver(SETTINGS.QUEUE_NAME)
        async with receiver:
            logger.info("Notification worker started. Listening for messages...")
            async for msg in receiver:
                db = SessionLocal()
                try:
                    data = _decode_message_body(msg)
                    if not data or data.get("source") != "orders_service":
                        await receiver.complete_message(msg)
                        continue

                    outbox_id = data.get("outbox_id")
                    if not outbox_id:
                        await receiver.complete_message(msg)
                        continue

                    outbox_uuid = uuid.UUID(outbox_id)
                    event = db.query(OutboxEvent).filter(OutboxEvent.id == outbox_uuid).first()
                    if not event or event.event_type != "purchase_request.vendor_notification":
                        await receiver.complete_message(msg)
                        continue

                    delivery = db.query(OutboxEventDelivery).filter(
                        OutboxEventDelivery.event_id == outbox_uuid,
                        OutboxEventDelivery.consumer == "notification_worker",
                    ).first()

                    if not delivery or delivery.status in ("completed", "failed"):
                        await receiver.complete_message(msg)
                        continue

                    delivery.status = "processing"
                    db.commit()

                    try:
                        _handle_vendor_notification(db, event)
                        delivery.status = "completed"
                        delivery.processed_at = datetime.now(timezone.utc)
                        db.commit()
                        await receiver.complete_message(msg)
                        logger.info(f"Processed vendor notification for outbox {outbox_id}")
                    except Exception as handler_exc:
                        db.rollback()
                        delivery = db.query(OutboxEventDelivery).filter(
                            OutboxEventDelivery.event_id == outbox_uuid,
                            OutboxEventDelivery.consumer == "notification_worker",
                        ).first()
                        if delivery:
                            delivery.retry_count = (delivery.retry_count or 0) + 1
                            delivery.error_message = str(handler_exc)[:500]
                            if delivery.retry_count >= (delivery.max_retries or 3):
                                delivery.status = "failed"
                                delivery.processed_at = datetime.now(timezone.utc)
                                db.commit()
                                await receiver.complete_message(msg)
                                logger.error(f"Vendor notification {outbox_id} failed after max retries: {handler_exc}")
                            else:
                                delivery.status = "pending"
                                db.commit()
                                await receiver.abandon_message(msg)
                                logger.warning(f"Retrying vendor notification {outbox_id}: {handler_exc}")

                except Exception as e:
                    logger.error(f"Notification worker error: {e}", exc_info=True)
                    try:
                        await receiver.complete_message(msg)
                    except Exception:
                        pass
                finally:
                    db.close()


async def _poll_fallback():
    """Fallback polling for local dev when service bus is not available."""
    POLL_INTERVAL = 5

    while True:
        db = SessionLocal()
        try:
            deliveries = (
                db.query(OutboxEventDelivery)
                .filter(
                    OutboxEventDelivery.consumer == "notification_worker",
                    OutboxEventDelivery.status == "pending",
                )
                .limit(10)
                .all()
            )

            for delivery in deliveries:
                event = db.query(OutboxEvent).filter(OutboxEvent.id == delivery.event_id).first()
                if not event:
                    delivery.status = "failed"
                    delivery.error_message = "Event not found"
                    db.commit()
                    continue

                delivery.status = "processing"
                db.commit()

                try:
                    _handle_vendor_notification(db, event)
                    delivery.status = "completed"
                    delivery.processed_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"[poll] Processed vendor notification for event {event.id}")
                except Exception as exc:
                    db.rollback()
                    delivery = db.query(OutboxEventDelivery).filter(
                        OutboxEventDelivery.id == delivery.id
                    ).first()
                    if delivery:
                        delivery.retry_count = (delivery.retry_count or 0) + 1
                        delivery.error_message = str(exc)[:500]
                        if delivery.retry_count >= (delivery.max_retries or 3):
                            delivery.status = "failed"
                            delivery.processed_at = datetime.now(timezone.utc)
                        else:
                            delivery.status = "pending"
                        db.commit()
                    logger.warning(f"[poll] Vendor notification failed: {exc}")
        except Exception as e:
            logger.error(f"[poll] Notification poll error: {e}", exc_info=True)
        finally:
            db.close()

        await asyncio.sleep(POLL_INTERVAL)
