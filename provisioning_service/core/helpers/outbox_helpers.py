"""
outbox_helpers.py
-----------------
Reusable helpers for creating OutboxEvent records and optionally dispatching
them to the Service Bus queue.

Usage
-----
    from provisioning_service.core.helpers.outbox_helpers import (
        create_outbox_event,
        dispatch_outbox_to_queue,
    )

    # Pure audit log (no queue):
    create_outbox_event(db, tenant_id, "site.created", {"site_id": ...})

    # Audit log + queue dispatch (heavy lifting):
    outbox = create_outbox_event(db, tenant_id, "product.created", {...})
    await dispatch_outbox_to_queue(outbox)
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent
from provisioning_service.utils.logger import logger


def create_outbox_event(
    db: Session,
    tenant_id: Any,
    event_type: str,
    event_data: Dict[str, Any],
    *,
    status: str = "completed",
) -> OutboxEvent:
    """
    Persist an OutboxEvent and return it.

    By default the status is ``"completed"`` because the primary intent for most
    endpoints is audit logging – the action has already succeeded synchronously.

    For events that need async worker processing, pass ``status="pending"`` so
    the outbox worker can pick them up.

    Args:
        db:          Active SQLAlchemy session (already inside a transaction).
        tenant_id:   UUID of the owning tenant (str or UUID).
        event_type:  Dot-notation event name, e.g. ``"product.created"``.
        event_data:  JSON-serialisable dict with relevant payload.
        status:      ``"completed"`` (audit only) or ``"pending"`` (needs worker).

    Returns:
        The persisted :class:`OutboxEvent` instance.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)

    event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status=status,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    # Flush so the row is visible within the same transaction but callers can
    # still include it in a larger commit.
    db.flush()
    return event


async def dispatch_outbox_to_queue(outbox: OutboxEvent) -> None:
    """
    Send the outbox event id to the Service Bus queue so a worker can process it.

    This is a best-effort call – failures are logged as warnings and do NOT
    raise, because the outbox record itself is the source of truth.
    """
    try:
        from provisioning_service.core.sb_client import messaging_service  # lazy import
        await messaging_service.send_outbox_message(str(outbox.id))
        logger.info(f"Dispatched outbox {outbox.id} ({outbox.event_type}) to queue")
    except Exception as exc:
        logger.warning(
            f"Failed to dispatch outbox {outbox.id} ({outbox.event_type}) to queue: {exc}"
        )

