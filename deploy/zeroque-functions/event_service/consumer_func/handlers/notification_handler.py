"""
Notification handler — sends alerts/notifications for specific events.

Example: email on user.created, Slack on order.placed, etc.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger("consumer.notification_handler")


async def handle(event: Dict[str, Any]) -> None:
    """Process events that require notifications."""
    event_type = event.get("event_type", "")
    logger.info(f"Notification handler: would notify for {event_type}")
