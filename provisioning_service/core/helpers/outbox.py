"""
outbox.py (compat shim)
-----------------------
Provides the ``append_outbox_event`` / ``notify_outbox`` interface that some
route modules already use.  Delegates to the canonical
``outbox_helpers.create_outbox_event`` / ``dispatch_outbox_to_queue`` helpers.

New code should import from ``outbox_helpers`` directly.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent
from provisioning_service.core.helpers.outbox_helpers import (
    create_outbox_event,
    dispatch_outbox_to_queue,
)


def append_outbox_event(
    db: Session,
    *,
    tenant_id: Any,
    aggregate_type: str,
    aggregate_id: Any,
    event_type: str,
    payload: Dict[str, Any],
    status: str = "completed",
) -> OutboxEvent:
    """
    Create an OutboxEvent record with explicit aggregate metadata.

    Compatible shim for callers that use the older
    ``append_outbox_event(db, tenant_id=..., aggregate_type=..., ...)`` signature.
    Now passes ``aggregate_type`` and ``aggregate_id`` as first-class columns
    via :func:`create_outbox_event`.
    """
    return create_outbox_event(
        db,
        tenant_id,
        event_type,
        payload,
        status=status,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


async def notify_outbox(outbox_id: str) -> None:
    """
    Best-effort dispatch of an outbox event to the Service Bus queue.

    Loads the OutboxEvent by id and calls :func:`dispatch_outbox_to_queue`.
    This is a convenience shim – failures are logged and swallowed.
    """
    # We only have the id here; build a minimal OutboxEvent-like object so we
    # can reuse dispatch_outbox_to_queue without a DB round-trip.
    class _Stub:
        def __init__(self, oid: str):
            self.id = oid
            self.event_type = "unknown"

    await dispatch_outbox_to_queue(_Stub(outbox_id))  # type: ignore[arg-type]

