import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from orders_service.Models import OutboxEvent, OutboxEventDelivery

_AGGREGATE_ID_KEYS = (
    "request_id",
    "task_id",
    "workflow_id",
    "cost_centre_id",
    "vendor_id",
    "category_id",
    "tenant_id",
)


def _determine_consumers(event_type: str, aggregate_type: str) -> list:
    consumers = ["graph_service"]

    if aggregate_type in {"purchase_request", "approval_task"}:
        # intelligence_service alias kept for backward compat; DIS is the
        # new canonical consumer name — both poll the same table with their
        # own consumer column value.
        consumers.append("intelligence_service")
        consumers.append("data_intelligence_service")

    if event_type == "purchase_request.vendor_notification":
        consumers.append("notification_worker")
    return consumers


def _derive_aggregate_type(event_type: str) -> str:
    return event_type.rsplit(".", 1)[0] if "." in event_type else event_type


def _derive_aggregate_id(event_data: Dict[str, Any]) -> Optional[uuid.UUID]:
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
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)

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
    db.flush()

    if status == "pending":
        for consumer_name in _determine_consumers(event_type, event.aggregate_type):
            db.add(
                OutboxEventDelivery(
                    id=uuid.uuid4(),
                    event_id=event.id,
                    consumer=consumer_name,
                    status="pending",
                    created_at=datetime.now(timezone.utc),
                )
            )
        db.flush()
        event.status = "dispatched"
        db.flush()

    return event

