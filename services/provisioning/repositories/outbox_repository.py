import json

from ..models import *
from .db_handler import SessionLocal
from ..models import OutboxEvent
from ..utils.provisioning_logger import logger

def store_outbox(db, evt_type, tid, eid, data):
    evt = OutboxEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        event_type=evt_type,
        aggregate_id=tid,
        event_data=json.dumps(data),
        status="pending",
        retry_count=0
    )
    db.add(evt)
    db.commit()
    return str(evt.event_id)

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