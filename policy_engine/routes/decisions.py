"""
Policy Decision Log API Routes
Endpoints for querying and auditing policy decisions.
"""
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from policy_engine.core.db_config import get_db
from policy_engine.engine.decision_logger import get_decisions, get_decision_by_id, cleanup_old_decisions
from policy_engine.Schemas import DecisionLogResponse, DecisionLogListResponse
from policy_engine.utils.logger import logger


router = APIRouter(prefix="/v1/policy-engine/decisions", tags=["Decision Audit"])


@router.get("", response_model=DecisionLogListResponse)
async def list_decisions(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    action: Optional[str] = Query(None, description="Filter by action"),
    decision: Optional[str] = Query(None, description="Filter by decision type (allowed, denied, approval_required)"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    from_date: Optional[datetime] = Query(None, description="Filter from date (ISO format)"),
    to_date: Optional[datetime] = Query(None, description="Filter to date (ISO format)"),
    correlation_id: Optional[str] = Query(None, description="Filter by correlation ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    List policy decision logs with filters.
    
    Used for auditing and compliance reporting.
    
    Supports filtering by:
    - tenant_id: Specific tenant
    - action: Specific action (e.g., 'order.create')
    - decision: Decision type (allowed, denied, approval_required)
    - user_id: Specific user
    - from_date / to_date: Date range
    - correlation_id: Request correlation for tracing
    """
    decisions, total = await get_decisions(
        db=db,
        tenant_id=tenant_id,
        action=action,
        decision_type=decision,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset
    )
    
    return DecisionLogListResponse(
        decisions=[DecisionLogResponse.model_validate(d) for d in decisions],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{decision_id}", response_model=DecisionLogResponse)
async def get_decision(
    decision_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific decision by ID.
    
    Returns the full decision details including:
    - Subject and resource context
    - Matched policies and rules
    - Decision outcome and reason
    - Evaluation timing
    """
    decision = await get_decision_by_id(db, decision_id)
    
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    
    return DecisionLogResponse.model_validate(decision)


@router.get("/correlation/{correlation_id}")
async def get_decisions_by_correlation(
    correlation_id: str,
    db: Session = Depends(get_db)
):
    """
    Get all decisions for a specific correlation ID.
    
    Useful for tracing all policy decisions made during
    a single request or transaction.
    """
    decisions, total = await get_decisions(
        db=db,
        correlation_id=correlation_id,
        limit=100,
        offset=0
    )
    
    return {
        "correlation_id": correlation_id,
        "decisions": [DecisionLogResponse.model_validate(d) for d in decisions],
        "total": total
    }


@router.get("/stats/summary")
async def get_decision_stats(
    tenant_id: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for policy decisions.
    
    Returns counts by decision type and action.
    """
    from sqlalchemy import func
    from policy_engine.Models import PolicyDecisionLog
    
    query = db.query(
        PolicyDecisionLog.decision,
        func.count(PolicyDecisionLog.decision_id).label('count')
    )
    
    if tenant_id:
        query = query.filter(PolicyDecisionLog.tenant_id == uuid.UUID(tenant_id))
    
    if from_date:
        query = query.filter(PolicyDecisionLog.evaluated_at >= from_date)
    
    if to_date:
        query = query.filter(PolicyDecisionLog.evaluated_at <= to_date)
    
    by_decision = query.group_by(PolicyDecisionLog.decision).all()
    
    # By action
    action_query = db.query(
        PolicyDecisionLog.action,
        func.count(PolicyDecisionLog.decision_id).label('count')
    )
    
    if tenant_id:
        action_query = action_query.filter(PolicyDecisionLog.tenant_id == uuid.UUID(tenant_id))
    
    if from_date:
        action_query = action_query.filter(PolicyDecisionLog.evaluated_at >= from_date)
    
    if to_date:
        action_query = action_query.filter(PolicyDecisionLog.evaluated_at <= to_date)
    
    by_action = action_query.group_by(PolicyDecisionLog.action).order_by(
        func.count(PolicyDecisionLog.decision_id).desc()
    ).limit(20).all()
    
    # Average evaluation time
    avg_query = db.query(
        func.avg(PolicyDecisionLog.evaluation_duration_ms).label('avg_ms')
    )
    
    if tenant_id:
        avg_query = avg_query.filter(PolicyDecisionLog.tenant_id == uuid.UUID(tenant_id))
    
    if from_date:
        avg_query = avg_query.filter(PolicyDecisionLog.evaluated_at >= from_date)
    
    if to_date:
        avg_query = avg_query.filter(PolicyDecisionLog.evaluated_at <= to_date)
    
    avg_result = avg_query.first()
    
    return {
        "by_decision": {row[0]: row[1] for row in by_decision},
        "by_action": {row[0]: row[1] for row in by_action},
        "avg_evaluation_ms": round(avg_result[0], 2) if avg_result and avg_result[0] else 0
    }


@router.post("/cleanup", status_code=200)
async def cleanup_decisions(
    db: Session = Depends(get_db)
):
    """
    Cleanup expired decision logs.
    
    This endpoint should be called periodically (e.g., via cron)
    to remove decisions past their retention date.
    
    Note: Requires admin privileges in production.
    """
    deleted_count = await cleanup_old_decisions(db)
    
    return {
        "message": "Cleanup completed",
        "deleted_count": deleted_count
    }
