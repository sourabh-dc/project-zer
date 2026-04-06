"""
event_service.local_runner
--------------------------
Local development runner — simulates the Azure Functions pipeline:
  1. Publisher loop: reads outbox → publishes to local transport
  2. Consumer loop: subscribes to topics → dispatches to graph handler → Neo4j

Usage:
    # Start Docker first: docker compose up -d postgres neo4j
    python3 -m event_service.local_runner
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import PUBLISHER_BATCH_SIZE, PUBLISHER_INTERVAL_SEC
from event_service.publisher import publish_pending_events
from event_service.transport import LocalTransport

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("local_runner")

TOPICS = ["tenant", "user"]


async def publisher_loop(transport: LocalTransport, interval: float):
    from shared.db import SessionFactory
    logger.info(f"Publisher: polling every {interval}s, batch={PUBLISHER_BATCH_SIZE}")
    while True:
        session = SessionFactory()
        try:
            count = await publish_pending_events(session, transport, PUBLISHER_BATCH_SIZE)
            if count:
                logger.info(f"Publisher: published {count} events")
        except Exception as exc:
            logger.error(f"Publisher error: {exc}")
        finally:
            session.close()
        await asyncio.sleep(interval)


def graph_consumer_handler(event):
    """Route events to graph_service handlers → Neo4j."""
    from graph_service.handlers import dispatch
    event_type = event.get("event_type", "unknown")
    handled = dispatch(event)
    status = "PROJECTED" if handled else "SKIPPED"
    logger.info(f"Consumer: {status} — {event_type}")


async def main():
    transport = LocalTransport()
    for topic in TOPICS:
        transport._get_queue(topic, "graph-consumer")

    tasks = [
        asyncio.create_task(publisher_loop(transport, PUBLISHER_INTERVAL_SEC)),
    ]
    for topic in TOPICS:
        tasks.append(
            asyncio.create_task(
                transport.subscribe(topic, "graph-consumer", graph_consumer_handler)
            )
        )

    logger.info(f"Local runner started — publisher + consumers on topics: {TOPICS}")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
