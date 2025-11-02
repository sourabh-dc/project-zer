# Outbox Pattern
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from services.entitlements.models import OutboxEvent, AuditLog, SubscriptionUsage


def store_outbox_event(db: Session, event_type: str, tenant_id: str, aggregate_id: Optional[str] = None, event_data: Dict[str, Any] = {}):
    outbox_event = OutboxEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        aggregate_id=aggregate_id or tenant_id,
        event_data=event_data,
        status="pending",
        retry_count=0
    )
    db.add(outbox_event)
    db.commit()
    return str(outbox_event.id)

# Audit Logging
def audit_log(db: Session, tenant_id: str, user_id: Optional[str], action: str, resource_type: str, resource_id: Optional[str], details: Optional[Dict] = None, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
    audit_entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(audit_entry)
    db.commit()

def get_current_usage(db, req):
    current_usage = db.query(SubscriptionUsage).filter(
        SubscriptionUsage.tenant_id == req.tenant_id,
        SubscriptionUsage.feature_code == req.feature_code,
        SubscriptionUsage.period_start <= datetime.now(timezone.utc),
        SubscriptionUsage.period_end >= datetime.now(timezone.utc)
    ).first()

    return current_usage