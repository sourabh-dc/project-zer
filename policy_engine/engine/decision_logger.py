"""
Decision Logger for Policy Engine
Logs all policy evaluation decisions for audit and compliance.
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from policy_engine.Models import PolicyDecisionLog
from policy_engine.core.config import SETTINGS
from policy_engine.utils.logger import logger


async def log_decision(
    db: Session,
    tenant_id: str,
    action: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    decision: Any,  # PolicyDecision dataclass
    duration_ms: int,
    correlation_id: Optional[str] = None,
    request_id: Optional[str] = None
) -> Optional[str]:
    """
    Log a policy decision to the database.
    
    Args:
        db: Database session
        tenant_id: Tenant ID
        action: The action that was evaluated
        subject: The subject context (who performed the action)
        resource: The resource context (what they acted on)
        context: Additional context
        decision: The PolicyDecision result
        duration_ms: Time taken to evaluate
        correlation_id: Optional correlation ID for tracing
        request_id: Optional request ID
        
    Returns:
        The decision_id if logged successfully, None otherwise
    """
    if not SETTINGS.ENABLE_DECISION_LOGGING:
        return None
    
    try:
        # Calculate retention date
        retention_until = datetime.now(timezone.utc) + timedelta(days=SETTINGS.DECISION_LOG_RETENTION_DAYS)
        
        # Sanitize subject to remove sensitive data
        sanitized_subject = _sanitize_for_logging(subject)
        
        # Build matched policies list
        matched_policies = []
        if hasattr(decision, 'matched_rules') and decision.matched_rules:
            matched_policies = decision.matched_rules
        
        decision_log = PolicyDecisionLog(
            decision_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id,
            action=action,
            subject=sanitized_subject,
            resource=resource,
            context=context,
            decision=decision.decision if hasattr(decision, 'decision') else str(decision),
            matched_policies=matched_policies,
            reason=decision.reason if hasattr(decision, 'reason') else None,
            approval_chain_id=uuid.UUID(decision.approval_chain_id) if hasattr(decision, 'approval_chain_id') and decision.approval_chain_id else None,
            evaluation_duration_ms=duration_ms,
            correlation_id=correlation_id,
            request_id=uuid.UUID(request_id) if request_id else None,
            retention_until=retention_until
        )
        
        db.add(decision_log)
        db.commit()
        
        logger.debug(f"Logged decision {decision_log.decision_id}: {action} -> {decision.decision}")
        
        return str(decision_log.decision_id)
        
    except Exception as e:
        logger.error(f"Failed to log decision: {e}")
        db.rollback()
        return None


def _sanitize_for_logging(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove sensitive fields from data before logging.
    
    Removes fields like passwords, tokens, API keys, etc.
    """
    sensitive_fields = {
        'password', 'password_hash', 'token', 'access_token', 'refresh_token',
        'api_key', 'secret', 'credentials', 'authorization'
    }
    
    if not isinstance(data, dict):
        return data
    
    sanitized = {}
    for key, value in data.items():
        if key.lower() in sensitive_fields:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_for_logging(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_for_logging(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    
    return sanitized


async def get_decisions(
    db: Session,
    tenant_id: Optional[str] = None,
    action: Optional[str] = None,
    decision_type: Optional[str] = None,
    user_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    correlation_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> tuple[List[PolicyDecisionLog], int]:
    """
    Query decision logs with filters.
    
    Returns:
        Tuple of (decisions list, total count)
    """
    try:
        query = db.query(PolicyDecisionLog)
        
        if tenant_id:
            query = query.filter(PolicyDecisionLog.tenant_id == uuid.UUID(tenant_id))
        
        if action:
            query = query.filter(PolicyDecisionLog.action == action)
        
        if decision_type:
            query = query.filter(PolicyDecisionLog.decision == decision_type)
        
        if user_id:
            # Filter by user_id in subject JSON
            query = query.filter(
                PolicyDecisionLog.subject['user_id'].astext == user_id
            )
        
        if from_date:
            query = query.filter(PolicyDecisionLog.evaluated_at >= from_date)
        
        if to_date:
            query = query.filter(PolicyDecisionLog.evaluated_at <= to_date)
        
        if correlation_id:
            query = query.filter(PolicyDecisionLog.correlation_id == correlation_id)
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        decisions = query.order_by(
            PolicyDecisionLog.evaluated_at.desc()
        ).offset(offset).limit(limit).all()
        
        return decisions, total
        
    except Exception as e:
        logger.error(f"Failed to query decisions: {e}")
        return [], 0


async def get_decision_by_id(db: Session, decision_id: str) -> Optional[PolicyDecisionLog]:
    """Get a specific decision by ID"""
    try:
        return db.query(PolicyDecisionLog).filter(
            PolicyDecisionLog.decision_id == uuid.UUID(decision_id)
        ).first()
    except Exception as e:
        logger.error(f"Failed to get decision {decision_id}: {e}")
        return None


async def cleanup_old_decisions(db: Session) -> int:
    """
    Delete decisions past their retention date.
    Should be called periodically (e.g., daily cron job).
    
    Returns:
        Number of decisions deleted
    """
    try:
        now = datetime.now(timezone.utc)
        result = db.query(PolicyDecisionLog).filter(
            PolicyDecisionLog.retention_until < now
        ).delete(synchronize_session=False)
        db.commit()
        
        if result > 0:
            logger.info(f"Cleaned up {result} expired decision logs")
        
        return result
    except Exception as e:
        logger.error(f"Failed to cleanup old decisions: {e}")
        db.rollback()
        return 0
