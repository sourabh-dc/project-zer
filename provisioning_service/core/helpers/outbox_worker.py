"""
Outbox worker — consumes Service Bus messages and routes to event handlers.

Engineering Lock v1.1 §3.2:
  - Events MUST NOT be marked processed until projection mutation completes.
  - If retries exceed threshold → dead-letter queue + operational alert.
  - Consumers MUST retry until success.

Engineering Lock v1.1 §0.3:
  - All projection consumers MUST be idempotent.
  - Duplicate event processing MUST NOT alter final state.
"""

import json
import uuid
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient

from provisioning_service.Models import OutboxEvent
from provisioning_service.core.db_config import SessionLocal
from provisioning_service.core.config import SETTINGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox-worker")


def _decode_message_body(msg):
    """Safely decode the service bus message body."""
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


HANDLER_REGISTRY = {}


def _load_handlers():
    """Lazy-load handler functions to avoid circular imports."""
    if HANDLER_REGISTRY:
        return
    from provisioning_service.core.tasks.tenant_worker import handle_tenant_created
    from provisioning_service.core.tasks.user_worker import handle_user_created

    HANDLER_REGISTRY["tenant.created"] = handle_tenant_created
    HANDLER_REGISTRY["user.created"] = handle_user_created


async def _process_event(db, event: OutboxEvent, outbox_id: str) -> None:
    """Route an outbox event to its handler. Raises on failure."""
    _load_handlers()

    handler = HANDLER_REGISTRY.get(event.event_type)
    if handler:
        logger.info(f"Routing outbox {outbox_id} → {event.event_type}")
        await handler(db, str(event.id))
    else:
        logger.info(f"No handler for event_type={event.event_type}; marking completed (no-op)")


async def process_outbox():
    """Main worker loop — consume Service Bus messages and process outbox events."""
    cred = DefaultAzureCredential()
    client = ServiceBusClient(SETTINGS.SB_NAMESPACE, cred)

    async with client:
        receiver = client.get_queue_receiver(SETTINGS.QUEUE_NAME)
        async with receiver:
            logger.info("Outbox worker started. Listening for messages...")
            async for msg in receiver:
                db = SessionLocal()
                try:
                    data = _decode_message_body(msg)
                    if not data:
                        logger.error("Empty/invalid message body; completing")
                        await receiver.complete_message(msg)
                        continue

                    outbox_id = data.get("outbox_id") or data.get("id")
                    if not outbox_id:
                        logger.error("No outbox_id in message; completing")
                        await receiver.complete_message(msg)
                        continue

                    try:
                        outbox_uuid = uuid.UUID(outbox_id)
                    except Exception:
                        logger.error("Invalid outbox_id format; completing")
                        await receiver.complete_message(msg)
                        continue

                    event = db.query(OutboxEvent).filter(OutboxEvent.id == outbox_uuid).first()
                    if not event:
                        logger.error(f"Outbox event {outbox_id} not found; completing")
                        await receiver.complete_message(msg)
                        continue

                    if event.processed_at is not None or event.status in ("completed", "dead_letter"):
                        logger.info(f"Outbox {outbox_id} already processed; completing")
                        await receiver.complete_message(msg)
                        continue

                    # Mark processing
                    event.status = "processing"
                    event.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    try:
                        await _process_event(db, event, outbox_id)

                        now = datetime.now(timezone.utc)
                        event.status = "completed"
                        event.processed_at = now
                        event.updated_at = now
                        db.commit()

                        await receiver.complete_message(msg)
                        logger.info(f"Processed outbox {outbox_id} successfully")

                    except Exception as handler_exc:
                        db.rollback()
                        event = db.query(OutboxEvent).filter(OutboxEvent.id == outbox_uuid).first()
                        if not event:
                            logger.error(f"Outbox {outbox_id} missing during error handling")
                            await receiver.complete_message(msg)
                            continue

                        event.retry_count = (event.retry_count or 0) + 1
                        event.updated_at = datetime.now(timezone.utc)

                        if event.retry_count >= (event.max_retries or 3):
                            event.status = "dead_letter"
                            event.processed_at = datetime.now(timezone.utc)
                            db.commit()
                            logger.error(
                                f"DEAD LETTER: outbox {outbox_id} (event_type={event.event_type}) "
                                f"failed after {event.retry_count} retries: {handler_exc}"
                            )
                            await receiver.complete_message(msg)
                        else:
                            db.commit()
                            logger.warning(
                                f"Transient error on outbox {outbox_id} "
                                f"(retry {event.retry_count}/{event.max_retries}): {handler_exc}"
                            )
                            await receiver.abandon_message(msg)

                except Exception as e:
                    logger.error(f"Unexpected worker error: {e}", exc_info=True)
                    try:
                        await receiver.complete_message(msg)
                    except Exception:
                        pass
                finally:
                    db.close()


async def run_relay_poller(interval_seconds: int = 10):
    """Relay poller — picks up outbox events that were never notified to Service Bus.

    Engineering Lock v1.1 §3.2: Events MUST be retried until success.
    This catches events where the initial Service Bus send failed.
    """
    from provisioning_service.core.sb_client import messaging_service

    logger.info(f"Relay poller started (interval={interval_seconds}s)")
    while True:
        db = SessionLocal()
        try:
            stale_cutoff = datetime.now(timezone.utc)
            pending_events = (
                db.query(OutboxEvent)
                .filter(
                    OutboxEvent.processed_at.is_(None),
                    OutboxEvent.status.in_(["pending", "processing"]),
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(50)
                .all()
            )

            if pending_events:
                logger.info(f"Relay poller found {len(pending_events)} unprocessed events")

            for event in pending_events:
                try:
                    await messaging_service.send_outbox_message(str(event.id))
                    logger.info(f"Relay: re-notified outbox {event.id}")
                except Exception as e:
                    logger.warning(f"Relay: failed to notify outbox {event.id}: {e}")

        except Exception as e:
            logger.error(f"Relay poller error: {e}", exc_info=True)
        finally:
            db.close()

        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(process_outbox())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
