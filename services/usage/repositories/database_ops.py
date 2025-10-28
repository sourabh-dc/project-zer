import json
import uuid

from services.usage.models import AuditLog, OutboxEvent
from ..utils.usage_logger import logger

def audit_log(db, tenant_id, user_id, action, entity_type, entity_id, changes=None):
    """Create audit log entry"""
    try:
        log = AuditLog(
            log_id=f"aud_{uuid.uuid4().hex[:12]}",
            aggregate_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Audit failed: {e}")

def store_outbox_event(db, event_type, tenant_id, entity_id, event_data):
    """Store event in outbox for reliable publishing"""
    evt = OutboxEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        event_type=event_type,
        aggregate_id=tenant_id,
        event_data=json.dumps(event_data),
        retry_count=0,
        status="pending"
    )
    db.add(evt)
    db.commit()
    return str(evt.event_id)