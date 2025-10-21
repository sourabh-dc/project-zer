import json
import uuid

from services.catalog.models import OutboxEvent
from .db_handler import SessionLocal


async def store_outbox_event(db, event_type, tenant_id, entity_id, event_data):
    """Store outbox event"""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    outbox_event = OutboxEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=tenant_id,
        event_data=json.dumps(event_data),
        status='pending'
    )
    db.add(outbox_event)
    db.commit()
    return event_id

def get_pending_events(limit=100):
    with SessionLocal() as db:
        return db.query(OutboxEvent).filter(
            OutboxEvent.status == "pending",
            OutboxEvent.retry_count < 5
        ).limit(limit).all()

def update_event_status(event, status, published_at=None):
    with SessionLocal() as db:
        event.status = status
        if published_at:
            event.published_at = published_at
        db.commit()