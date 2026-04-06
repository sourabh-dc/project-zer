"""
Vector handler — calls the vector service to generate/update embeddings.

Only processes product and category events (semantic search relevant).
"""
import logging
from typing import Any, Dict

logger = logging.getLogger("consumer.vector_handler")

SUPPORTED_AGGREGATES = {"product", "category"}


async def handle(event: Dict[str, Any]) -> None:
    """Process product/category events for embedding generation."""
    agg_type = event.get("aggregate_type", "")
    if agg_type not in SUPPORTED_AGGREGATES:
        logger.debug(f"Vector handler: skipping {event.get('event_type')} (not product/category)")
        return

    logger.info(
        f"Vector handler: would generate embedding for {event.get('event_type')} "
        f"(event_id={event.get('event_id')})"
    )
