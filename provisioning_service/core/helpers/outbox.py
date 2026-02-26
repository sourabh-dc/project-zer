"""
Outbox helper — atomic event appending and Service Bus notification.

Engineering Lock v1.1 §3.2:
  Events MUST be appended in the same transaction as the aggregate change.
  This module provides a single function to add an OutboxEvent to the current
  DB session (caller commits once for both entity + event) and a best-effort
  Service Bus notification.
"""

import uuid
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent
from provisioning_service.utils.logger import logger


def append_outbox_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: Dict[str, Any],
) -> OutboxEvent:
    """Add an OutboxEvent to the session. Caller MUST commit in the same TX as the aggregate write.

    Returns the (not-yet-committed) OutboxEvent so the caller can read its ``id``
    after commit for the Service Bus notification.
    """
    event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        status="pending",
        retry_count=0,
        max_retries=3,
    )
    db.add(event)
    return event


async def notify_outbox(outbox_id: str) -> None:
    """Best-effort Service Bus notification. If this fails the relay poller will catch it."""
    try:
        from provisioning_service.core.sb_client import messaging_service
        await messaging_service.send_outbox_message(outbox_id)
    except Exception as e:
        logger.warning(f"Service Bus notification failed for outbox {outbox_id} (relay will retry): {e}")
