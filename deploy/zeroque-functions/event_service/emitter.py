"""
event_service.emitter
---------------------
Single function to emit a domain event into the outbox.

Called inside the API layer's DB transaction — the event is atomically
committed with the business data, guaranteeing at-least-once delivery.

Topic routing:
  - event_type prefix determines the Service Bus topic
  - tenant.created → topic "tenant"
  - user.created   → topic "user"
  - site.created   → topic "site"
  - etc.
"""
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("event_service.emitter")

_AGGREGATE_ID_KEYS = (
    "site_id", "store_id", "user_id", "vendor_id", "cost_centre_id",
    "org_unit_id", "tenant_id", "product_id", "category_id", "order_id",
    "role_id", "subscription_id", "policy_id", "po_id",
)


def _derive_aggregate_type(event_type: str) -> str:
    return event_type.rsplit(".", 1)[0] if "." in event_type else event_type


def _derive_aggregate_id(payload: Dict[str, Any]) -> Optional[str]:
    for key in _AGGREGATE_ID_KEYS:
        val = payload.get(key)
        if val is not None:
            try:
                return str(uuid.UUID(str(val)))
            except (ValueError, AttributeError):
                continue
    return None


def _derive_topic(event_type: str) -> str:
    """Route events to Service Bus topics by type prefix.

    tenant.created → "tenant"
    user.created   → "user"
    site.created   → "site"
    """
    return event_type.split(".")[0] if "." in event_type else event_type


def emit(
    db: Session,
    tenant_id: Any,
    event_type: str,
    payload: Dict[str, Any],
    *,
    topic: Optional[str] = None,
    aggregate_type: Optional[str] = None,
    aggregate_id: Optional[str] = None,
) -> str:
    """Write an event to the outbox_events table.

    Uses raw SQL so it has zero ORM dependency and works with any
    SQLAlchemy session. The row is part of the caller's transaction —
    call ``db.commit()`` after this to persist atomically.

    Returns the event UUID as a string.
    """
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    tid = str(tenant_id) if not isinstance(tenant_id, uuid.UUID) else str(tenant_id)
    agg_type = aggregate_type or _derive_aggregate_type(event_type)
    agg_id = aggregate_id or _derive_aggregate_id(payload)
    resolved_topic = topic or _derive_topic(event_type)

    db.execute(
        text("""
            INSERT INTO outbox_events
                (id, tenant_id, event_type, aggregate_type, aggregate_id,
                 payload, status, topic, retry_count, max_retries, created_at)
            VALUES
                (:id, :tenant_id, :event_type, :agg_type, :agg_id,
                 :payload, 'pending', :topic, 0, 5, :now)
        """),
        {
            "id": event_id,
            "tenant_id": uuid.UUID(tid),
            "event_type": event_type,
            "agg_type": agg_type,
            "agg_id": uuid.UUID(agg_id) if agg_id else None,
            "payload": json.dumps(payload),
            "topic": resolved_topic,
            "now": now,
        },
    )

    logger.info(f"Event queued: {event_type} (id={event_id}, topic={resolved_topic})")
    return str(event_id)
