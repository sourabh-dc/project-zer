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
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent, OutboxEventDelivery
from provisioning_service.utils.logger import logger

# Keys commonly used in event_data that hold the aggregate entity's ID.
# Checked in priority order: the first match wins.
_AGGREGATE_ID_KEYS = (
    "product_id", "category_id", "variant_id", "store_product_id",
    "site_id", "store_id", "user_id", "vendor_id", "cost_centre_id",
    "org_unit_id", "tenant_id", "subscription_id", "policy_id",
    "request_id", "calendar_id", "year_id", "period_id",
    "role_id", "assignment_id", "cap_id", "version_id",
    "target_version_id", "from_version_id", "source_version_id",
    "approved_range_id", "change_req_id", "limit_id", "task_id",
)

# ── Consumer routing rules ────────────────────────────────────────
# Only applied when status='pending' (actionable events, not audit-only).

_OUTBOX_WORKER_EVENT_TYPES = frozenset({
    'tenant.signup',
    'user.created',
    'product.created',
    'product.bulk_created',
    'mandate.created',
    'mandate.activated',
})

_VECTOR_SERVICE_AGGREGATE_TYPES = frozenset({
    'product',
    'category',
})

# Aggregate types that the data_intelligence_service needs to keep its
# derived knowledge layer and graph projections in sync.
# The DIS outbox consumer polls for consumer='data_intelligence_service'
# delivery rows, so it will never receive events unless we create rows here.
_DATA_INTELLIGENCE_AGGREGATE_TYPES = frozenset({
    'product',
    'category',
    'approved_range',
    'budget',
    'policy',
    'policy_rule',
    'policy_assignment',
    'org_unit',
    'user',
    'role',
    'role_permission',
    'vendor',
    'tenant',
    'site',
    'store',
    'cost_centre',
    'mandate',
})


def _determine_consumers(event_type: str, aggregate_type: str) -> list:
    """Return the list of consumer names that should receive delivery rows."""
    consumers = []

    if event_type in _OUTBOX_WORKER_EVENT_TYPES:
        consumers.append('outbox_worker')

    # graph_service gets ALL pending events — keeps Neo4j in sync
    consumers.append('graph_service')

    if aggregate_type in _VECTOR_SERVICE_AGGREGATE_TYPES:
        consumers.append('vector_service')

    # data_intelligence_service keeps its derived knowledge layer in sync
    # for entities that affect intelligence query results (approved ranges,
    # policies, budgets, org structure, products).
    if aggregate_type in _DATA_INTELLIGENCE_AGGREGATE_TYPES:
        consumers.append('data_intelligence_service')

    return consumers


def _derive_aggregate_type(event_type: str) -> str:
    """Derive aggregate_type from dot-notation event_type.

    ``"product.created"`` → ``"product"``
    ``"approval_task.approved"`` → ``"approval_task"``
    """
    return event_type.rsplit(".", 1)[0] if "." in event_type else event_type


def _derive_aggregate_id(event_data: Dict[str, Any]) -> Optional[uuid.UUID]:
    """Scan event_data for a well-known entity ID key and return it as UUID."""
    for key in _AGGREGATE_ID_KEYS:
        val = event_data.get(key)
        if val is not None:
            try:
                return uuid.UUID(str(val))
            except (ValueError, AttributeError):
                continue
    return None


def create_outbox_event(
    db: Session,
    tenant_id: Any,
    event_type: str,
    event_data: Dict[str, Any],
    *,
    status: str = "completed",
    aggregate_type: Optional[str] = None,
    aggregate_id: Any = None,
) -> OutboxEvent:
    """
    Persist an OutboxEvent and return it.

    By default the status is ``"completed"`` because the primary intent for most
    endpoints is audit logging – the action has already succeeded synchronously.

    For events that need async worker processing, pass ``status="pending"`` so
    the outbox worker can pick them up.

    ``aggregate_type`` and ``aggregate_id`` are auto-derived when not supplied:

    * ``aggregate_type`` ← prefix of *event_type* (e.g. ``"product"`` from
      ``"product.created"``)
    * ``aggregate_id`` ← first recognised entity-ID key found in *event_data*

    Args:
        db:              Active SQLAlchemy session (already inside a transaction).
        tenant_id:       UUID of the owning tenant (str or UUID).
        event_type:      Dot-notation event name, e.g. ``"product.created"``.
        event_data:      JSON-serialisable dict with relevant payload.
        status:          ``"completed"`` (audit only) or ``"pending"`` (needs worker).
        aggregate_type:  Optional entity type (auto-derived from event_type if omitted).
        aggregate_id:    Optional entity UUID (auto-derived from event_data if omitted).

    Returns:
        The persisted :class:`OutboxEvent` instance.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)

    # Auto-derive aggregate metadata when not explicitly provided
    if aggregate_type is None:
        aggregate_type = _derive_aggregate_type(event_type)

    resolved_agg_id: Optional[uuid.UUID] = None
    if aggregate_id is not None:
        try:
            resolved_agg_id = uuid.UUID(str(aggregate_id))
        except (ValueError, AttributeError):
            resolved_agg_id = None
    else:
        resolved_agg_id = _derive_aggregate_id(event_data)

    event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=resolved_agg_id,
        event_type=event_type,
        payload=event_data,
        status=status,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    # Flush so the row is visible within the same transaction but callers can
    # still include it in a larger commit.
    db.flush()

    # Create delivery rows for each consumer that should process this event
    if status == "pending":
        consumers = _determine_consumers(event_type, event.aggregate_type)
        for consumer_name in consumers:
            delivery = OutboxEventDelivery(
                id=uuid.uuid4(),
                event_id=event.id,
                consumer=consumer_name,
                status='pending',
                created_at=datetime.now(timezone.utc),
            )
            db.add(delivery)
        db.flush()
        # Mark the outbox event as dispatched — consumers now read from
        # outbox_event_delivery, not outbox_events.status
        event.status = 'dispatched'
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

