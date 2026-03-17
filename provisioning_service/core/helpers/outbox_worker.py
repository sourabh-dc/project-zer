import json
import uuid
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path for direct script execution
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Use the ASYNC versions for Service Bus
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient

# Your internal imports
from provisioning_service.Models import (
    OutboxEvent,
    OutboxEventDelivery,
)
from provisioning_service.core.db_config import SessionLocal

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

SB_NAMESPACE = "zeroque.servicebus.windows.net"
QUEUE_NAME = "outbox-task-queue"


def _decode_message_body(msg):
    """Safely decode the service bus message body to a Python object.
    Handles cases where `msg.body` yields an iterable of bytes/strings.
    """
    try:
        # msg.body may be an iterable of bytes/parts
        body_bytes = b""
        if hasattr(msg, "body"):
            for part in msg.body:
                if isinstance(part, (bytes, bytearray)):
                    body_bytes += bytes(part)
                else:
                    body_bytes += str(part).encode("utf-8")
        else:
            # fallback to str(msg)
            body_bytes = str(msg).encode("utf-8")

        text = body_bytes.decode("utf-8")
        return json.loads(text)
    except Exception as exc:
        logger.error(f"Failed to decode message body: {exc}")
        return None


async def process_outbox():
    """Generic outbox processor. Routes based on OutboxEvent.event_type to handler functions.

    Workflow:
    - Receive Service Bus message containing {'outbox_id': '<uuid>'}
    - Load OutboxEvent from DB for payload/event_type
    - Look up the outbox_worker delivery row in outbox_event_delivery
    - Mark delivery as processing, call handler, mark completed/failed
    """
    cred = DefaultAzureCredential()
    client = ServiceBusClient(SB_NAMESPACE, cred)

    async with client:
        receiver = client.get_queue_receiver(QUEUE_NAME)
        async with receiver:
            logger.info("Outbox worker started. Listening for messages...")
            async for msg in receiver:
                db = SessionLocal()

                try:
                    data = _decode_message_body(msg)
                    if not data:
                        logger.error("Empty/invalid message body; completing message")
                        await receiver.complete_message(msg)
                        continue

                    outbox_id = data.get("outbox_id") or data.get("id")
                    if not outbox_id:
                        logger.error("No outbox_id found in message; completing message")
                        await receiver.complete_message(msg)
                        continue

                    try:
                        outbox_uuid = uuid.UUID(outbox_id)
                    except Exception:
                        logger.error("Invalid outbox_id format; completing message")
                        await receiver.complete_message(msg)
                        continue

                    event = db.query(OutboxEvent).filter(OutboxEvent.id == outbox_uuid).first()
                    if not event:
                        logger.error(f"Outbox event not found for id {outbox_id}; completing message")
                        await receiver.complete_message(msg)
                        continue

                    # Look up this consumer's delivery row
                    delivery = db.query(OutboxEventDelivery).filter(
                        OutboxEventDelivery.event_id == outbox_uuid,
                        OutboxEventDelivery.consumer == 'outbox_worker',
                    ).first()

                    if not delivery:
                        logger.warning(f"No delivery row for outbox_worker event {outbox_id}; completing message")
                        await receiver.complete_message(msg)
                        continue

                    # Skip if already processed
                    if delivery.status in ('completed', 'failed'):
                        logger.info(f"Delivery for {outbox_id} already {delivery.status}; completing message")
                        await receiver.complete_message(msg)
                        continue

                    # Mark processing on the delivery row
                    delivery.status = 'processing'
                    db.commit()

                    # Route to handler based on event_type
                    try:
                        logger.info(f"Routing outbox {outbox_id} with event_type={event.event_type}")
                        if event.event_type == "tenant.signup":
                            # lazy import to avoid circular/import-time issues
                            from provisioning_service.core.tasks.tenant_worker import handle_tenant_provisioning
                            # pass payload id (outbox id) to handler per requested call pattern
                            await handle_tenant_provisioning(db, str(event.id))

                        elif event.event_type == "user.created":
                            from provisioning_service.core.tasks.user_worker import handle_user_created
                            await handle_user_created(db, str(event.id))

                        elif event.event_type == "product.created":
                            from provisioning_service.core.tasks.product_worker import handle_product_created
                            await handle_product_created(db, str(event.id))

                        elif event.event_type == "product.bulk_created":
                            from provisioning_service.core.tasks.product_worker import handle_bulk_products_created
                            await handle_bulk_products_created(db, str(event.id))

                        else:
                            logger.warning(f"No handler implemented for event_type={event.event_type}; marking completed")

                        # On success — mark delivery completed
                        delivery.status = 'completed'
                        delivery.processed_at = datetime.now(timezone.utc)
                        db.commit()

                        await receiver.complete_message(msg)
                        logger.info(f"Processed outbox {outbox_id} successfully")

                    except Exception as handler_exc:
                        # Handler raised; apply retry logic on delivery row
                        db.rollback()
                        delivery = db.query(OutboxEventDelivery).filter(
                            OutboxEventDelivery.event_id == outbox_uuid,
                            OutboxEventDelivery.consumer == 'outbox_worker',
                        ).first()
                        if delivery:
                            delivery.retry_count = (delivery.retry_count or 0) + 1
                            delivery.error_message = str(handler_exc)[:500]
                            if delivery.retry_count >= (delivery.max_retries or 3):
                                delivery.status = 'failed'
                                delivery.processed_at = datetime.now(timezone.utc)
                                db.commit()
                                logger.error(f"Delivery for {outbox_id} failed after max retries: {handler_exc}")
                                await receiver.complete_message(msg)
                            else:
                                delivery.status = 'pending'
                                db.commit()
                                logger.error(f"Transient error for {outbox_id}, abandoning for retry: {handler_exc}")
                                await receiver.abandon_message(msg)
                        else:
                            logger.error(f"Delivery row missing during error handling for id {outbox_id}: {handler_exc}")
                            await receiver.complete_message(msg)

                except Exception as e:
                    logger.error(f"Unexpected worker error: {e}", exc_info=True)
                    try:
                        await receiver.complete_message(msg)
                    except Exception:
                        pass
                finally:
                    db.close()


if __name__ == "__main__":
    try:
        asyncio.run(process_outbox())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
