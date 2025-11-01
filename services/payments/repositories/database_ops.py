from typing import Dict, Any
from sqlalchemy.orm import Session

from services.payments.models import AuditLog


async def log_audit(db: Session, action: str, resource_type: str, resource_id: str = None,
                   details: Dict[str, Any] = None, tenant_id: str = None, user_id: str = None):
    """Log audit event"""
    audit_log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit_log)
    db.commit()