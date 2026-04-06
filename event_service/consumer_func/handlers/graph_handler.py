"""
Graph handler — calls the graph service API to project entities into Neo4j.

Each event type maps to a graph service endpoint. The handler transforms
the event payload into the API call format and invokes it.
"""
import logging
from typing import Any, Dict

import httpx

from shared.config import GRAPH_SERVICE_URL

logger = logging.getLogger("consumer.graph_handler")


async def handle(event: Dict[str, Any]) -> None:
    """Route an event to the graph service for Neo4j projection."""
    event_type = event.get("event_type", "")
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id", "")

    body = {
        "event_id": event.get("event_id"),
        "event_type": event_type,
        "tenant_id": tenant_id,
        "aggregate_type": event.get("aggregate_type"),
        "aggregate_id": event.get("aggregate_id"),
        "payload": payload,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{GRAPH_SERVICE_URL}/graph/ingest",
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Graph service returned {resp.status_code}: {resp.text[:200]}"
            )

    logger.info(f"Graph handler: processed {event_type} (event_id={event.get('event_id')})")
