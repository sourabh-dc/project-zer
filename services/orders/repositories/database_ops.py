import json
import uuid

from sqlalchemy import text

from services.orders.models import AuditLog
from services.orders.utils.orders_logger import logger


def store_outbox(db, event_type, tenant_id, entity_id, event_data):
    """Store outbox event"""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    # Use direct SQL to avoid schema caching issues
    db.execute(text("""
        INSERT INTO outbox_events 
        (event_id, event_type, aggregate_id, event_data, status, retry_count, event_version, max_retries)
        VALUES (:eid, :etype, :aid, :data, 'pending', 0, 1, 3)
    """), {
        "eid": event_id,
        "etype": event_type,
        "aid": tenant_id,
        "data": json.dumps(event_data)
    })
    return event_id

def audit(db, tenant_id, user_id, action, entity_type, entity_id, changes):
    """Audit logging"""
    try:
        log_id = f"aud_{uuid.uuid4().hex[:12]}"
        audit_log = AuditLog(
            log_id=log_id,
            aggregate_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=json.dumps(changes) if changes else None
        )
        db.add(audit_log)
        db.commit()
    except Exception as e:
        logger.warning("Audit failed", error=str(e))