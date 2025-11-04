from sqlalchemy.orm import Session

from services.ledger.models import AuditLog, OutboxEvent


async def log_audit(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: str = None,
    details: dict = None,
    user_id: str = None,
    tenant_id: str = None,
    ip_address: str = None,
    user_agent: str = None
):
    """Log audit trail"""
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(audit)
    db.commit()

async def publish_event(
    db: Session,
    event_type: str,
    event_data: dict,
    tenant_id: str = None
):
    """Publish event using outbox pattern"""
    outbox_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data
    )
    db.add(outbox_event)
    db.commit()