"""
Azure Function — Event Consumer (Service Bus Triggers)

Two topics:
  - "tenant" — tenant lifecycle events → Neo4j graph projection
  - "user"   — user lifecycle events → Neo4j graph projection

Each trigger deserialises the message, calls the graph_service dispatcher
which executes Cypher against Neo4j to create/update nodes and relationships.
"""
import json
import logging

import azure.functions as func

app = func.FunctionApp()

logger = logging.getLogger("consumer_func")


def _process_event(message: func.ServiceBusMessage, consumer_name: str) -> None:
    """Shared processing: deserialise → dispatch to graph handler → log."""
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
