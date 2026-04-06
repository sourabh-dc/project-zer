"""
event_service.transport
-----------------------
Pluggable message transport — abstracts the message broker so the publisher
and consumer code works identically in local dev and Azure production.

Two implementations:
    LocalTransport      — in-process asyncio queues (for testing / local dev)
    ServiceBusTransport — Azure Service Bus topics/subscriptions (production)

Usage::

    transport = create_transport()          # reads TRANSPORT_MODE from config
    await transport.publish("domain-events", event_dict)
    await transport.subscribe("domain-events", "graph-sub", handler_fn)
"""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("event_service.transport")


class EventTransport(ABC):
    """Abstract base for event transports."""

    @abstractmethod
    async def publish(self, topic: str, events: List[Dict[str, Any]]) -> int:
        """Publish a batch of events to a topic. Returns count published."""
        ...

    @abstractmethod
    async def subscribe(
        self, topic: str, subscription: str, handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """Subscribe to a topic and process events through handler. Blocks."""
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ── Local Transport (asyncio queues) ─────────────────────────────────

class LocalTransport(EventTransport):
    """In-process transport using asyncio queues. One queue per subscription."""

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._running = True

    def _get_queue(self, topic: str, subscription: str) -> asyncio.Queue:
        key = f"{topic}::{subscription}"
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
        return self._queues[key]

    async def publish(self, topic: str, events: List[Dict[str, Any]]) -> int:
        count = 0
        for event in events:
            for key, q in self._queues.items():
                if key.startswith(f"{topic}::"):
                    await q.put(event)
                    count += 1
        logger.info(f"[LocalTransport] Published {len(events)} events to {topic} ({count} deliveries)")
        return count

    async def subscribe(
        self, topic: str, subscription: str, handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        q = self._get_queue(topic, subscription)
        logger.info(f"[LocalTransport] Subscribed: {topic}/{subscription}")
        while self._running:
            try:
                event = await asyncio.wait_for(q.get(), timeout=1.0)
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                    logger.info(f"[LocalTransport] Processed {event.get('event_type')} via {subscription}")
                except Exception as exc:
                    logger.error(f"[LocalTransport] Handler error in {subscription}: {exc}")
            except asyncio.TimeoutError:
                continue

    async def close(self) -> None:
        self._running = False


# ── Azure Service Bus Transport ───────────────────────────────────────

class ServiceBusTransport(EventTransport):
    """Azure Service Bus transport using topics and subscriptions.

    Requires ``azure-servicebus`` package and a valid connection string.
    Topics and subscriptions must be pre-created in Azure (or via Terraform/Bicep).
    """

    def __init__(self, connection_string: str):
        from azure.servicebus import ServiceBusClient
        self._conn_str = connection_string
        self._client = ServiceBusClient.from_connection_string(connection_string)

    async def publish(self, topic: str, events: List[Dict[str, Any]]) -> int:
        from azure.servicebus import ServiceBusMessage
        sender = self._client.get_topic_sender(topic_name=topic)
        try:
            messages = [
                ServiceBusMessage(
                    body=json.dumps(evt),
                    content_type="application/json",
                    subject=evt.get("event_type", "unknown"),
                    application_properties={
                        "event_type": evt.get("event_type", ""),
                        "tenant_id": evt.get("tenant_id", ""),
                        "aggregate_type": evt.get("aggregate_type", ""),
                    },
                )
                for evt in events
            ]
            sender.send_messages(messages)
            logger.info(f"[ServiceBus] Published {len(messages)} events to topic '{topic}'")
            return len(messages)
        finally:
            sender.close()

    async def subscribe(
        self, topic: str, subscription: str, handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """Long-running subscription loop.

        In production this is replaced by the Azure Function's SB trigger,
        but this method is useful for local testing with a real SB namespace.
        """
        receiver = self._client.get_subscription_receiver(
            topic_name=topic, subscription_name=subscription, max_wait_time=5,
        )
        logger.info(f"[ServiceBus] Subscribed: {topic}/{subscription}")
        try:
            while True:
                messages = receiver.receive_messages(max_message_count=10, max_wait_time=5)
                for msg in messages:
                    try:
                        event = json.loads(str(msg))
                        result = handler(event)
                        if asyncio.iscoroutine(result):
                            await result
                        receiver.complete_message(msg)
                    except Exception as exc:
                        logger.error(f"[ServiceBus] Handler error: {exc}")
                        receiver.abandon_message(msg)
                if not messages:
                    await asyncio.sleep(1)
        finally:
            receiver.close()

    async def close(self) -> None:
        self._client.close()


# ── Factory ───────────────────────────────────────────────────────────

def create_transport(mode: Optional[str] = None) -> EventTransport:
    """Create a transport instance based on configuration.

    Args:
        mode: "local" or "servicebus". Defaults to TRANSPORT_MODE from config.
    """
    from shared.config import TRANSPORT_MODE, SERVICE_BUS_CONNECTION

    resolved = mode or TRANSPORT_MODE
    if resolved == "servicebus":
        if not SERVICE_BUS_CONNECTION:
            raise ValueError("SERVICE_BUS_CONNECTION is required for servicebus transport")
        return ServiceBusTransport(SERVICE_BUS_CONNECTION)
    else:
        return LocalTransport()
