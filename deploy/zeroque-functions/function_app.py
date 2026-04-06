"""
ZeroQue Azure Functions — Combined Publisher + Consumer

Functions:
  1. outbox_publisher (Timer, every 10s)
     → Reads pending events from Postgres outbox → publishes to Service Bus

  2. tenant_consumer (Service Bus topic trigger: "tenant")
     → Consumes tenant events → projects to Neo4j graph

  3. user_consumer (Service Bus topic trigger: "user")
     → Consumes user events → projects to Neo4j graph (+ Role + HAS_ROLE)
"""
import asyncio
import json
import logging
import os
import sys

import azure.functions as func

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = func.FunctionApp()
logger = logging.getLogger("zeroque_functions")


# ── Publisher ─────────────────────────────────────────────────────────

@app.timer_trigger(
    schedule="*/10 * * * * *",
    arg_name="timer",
    run_on_startup=False,
)
async def outbox_publisher(timer: func.TimerRequest) -> None:
    """Timer-triggered outbox publisher — runs every 10 seconds."""
    if timer.past_due:
        logger.warning("Publisher timer is past due, executing anyway")

    from shared.db import SessionFactory
    from event_service.publisher import publish_pending_events
    from event_service.transport import create_transport

    transport = create_transport("servicebus")
    session = SessionFactory()

    try:
        batch_size = int(os.getenv("PUBLISHER_BATCH_SIZE", "100"))
        count = await publish_pending_events(session, transport, batch_size)
        if count > 0:
            logger.info(f"Published {count} events to Service Bus")
    except Exception as exc:
        logger.error(f"Publisher cycle failed: {exc}", exc_info=True)
    finally:
        session.close()
        await transport.close()


# ── Consumers ─────────────────────────────────────────────────────────

def _process_event(message: func.ServiceBusMessage, consumer_name: str) -> None:
    """Shared: deserialise → graph handler → Neo4j."""
    raw = message.get_body().decode("utf-8")
    event = json.loads(raw)

    event_type = event.get("event_type", "unknown")
    tenant_id = event.get("tenant_id", "?")
    event_id = event.get("event_id", "?")

    from graph_service.handlers import dispatch
    handled = dispatch(event)

    status = "PROJECTED" if handled else "SKIPPED"
    logger.info(
        "[%s] %s — %s | tenant_id=%s | event_id=%s",
        consumer_name, status, event_type, tenant_id, event_id,
    )


@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="tenant",
    subscription_name="tenant-consumer",
    connection="SERVICE_BUS_CONNECTION",
)
async def tenant_consumer(message: func.ServiceBusMessage) -> None:
    """Process tenant lifecycle events → Neo4j graph projection."""
    _process_event(message, "tenant-consumer")


@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="user",
    subscription_name="user-consumer",
    connection="SERVICE_BUS_CONNECTION",
)
async def user_consumer(message: func.ServiceBusMessage) -> None:
    """Process user lifecycle events → Neo4j graph projection."""
    _process_event(message, "user-consumer")
