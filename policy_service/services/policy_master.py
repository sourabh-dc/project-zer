"""
Policy Master — read-only endpoints for visibility into policy state.

Policies are defined statically as Rego files in shared/opa_policies/.
No policy creation, update, or deletion is permitted through the API.

Endpoints:
  GET  /policies                              — list policies stored in DB (audit visibility)
  GET  /policies/{policy_id}                  — get a single policy
  GET  /policies/{policy_id}/assignments      — list policy assignments
  GET  /policy-decisions                      — audit log of past decisions
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from policy_service.Models import Policy, PolicyVersion, PolicyAssignment, PolicyDecisionLog
from policy_service.core.db_config import get_db
from policy_service.utils.logger import logger

router = APIRouter(tags=["Policy Management"])


# =====================================================================
# Helpers
# =====================================================================

def _policy_to_response(policy: Policy) -> dict:
    """Serialise a Policy ORM object to a response dict."""
    current_ver = None
    for v in (policy.versions or []):
        if v.effective_until is None:
            current_ver = v
            break

    ver_resp = None
    if current_ver:
        ver_resp = {
            "version_id": current_ver.version_id,
            "policy_id": current_ver.policy_id,
            "version_number": current_ver.version_number,
            "effective_from": current_ver.effective_from,
            "effective_until": current_ver.effective_until,
            "change_reason": current_ver.change_reason,
            "created_at": current_ver.created_at,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "version_id": r.version_id,
                    "rule_order": r.rule_order,
                    "name": r.name,
                    "condition_expression": r.condition_expression,
                    "effect": r.effect,
                    "denial_reason": r.denial_reason,
                    "approval_chain_id": r.approval_chain_id,
                    "actions": r.actions,
                    "is_active": r.is_active,
                    "created_at": r.created_at,
                }
                for r in (current_ver.rules or [])
                if r.is_active
            ],
        }

    return {
        "policy_id": policy.policy_id,
        "tenant_id": policy.tenant_id,
        "code": policy.code,
        "name": policy.name,
        "description": policy.description,
        "policy_type": policy.policy_type,
        "priority": policy.priority,
        "is_active": policy.is_active,
        "status": policy.status,
        "created_by": policy.created_by,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
        "current_version": ver_resp,
    }


# =====================================================================
# READ-ONLY POLICY ENDPOINTS
# =====================================================================

@router.get("/policies")
async def list_policies(
    tenant_id: Optional[str] = Query(None),
    policy_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List policies with optional filters (read-only visibility)."""
    q = db.query(Policy)
    if tenant_id:
        q = q.filter((Policy.tenant_id == uuid.UUID(tenant_id)) | (Policy.tenant_id == None))
    if policy_type:
        q = q.filter(Policy.policy_type == policy_type)
    if is_active is not None:
        q = q.filter(Policy.is_active == is_active)

    total = q.count()
    policies = (
        q.options(joinedload(Policy.versions).joinedload(PolicyVersion.rules))
        .order_by(Policy.priority, Policy.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    seen = set()
    unique_policies = []
    for p in policies:
        if p.policy_id not in seen:
            seen.add(p.policy_id)
            unique_policies.append(p)

    return {
        "policies": [_policy_to_response(p) for p in unique_policies],
        "total": total,
        "skip": skip,
        "limit": limit,
        "note": "Policies are defined as Rego files in shared/opa_policies/. This list reflects the DB audit record only.",
    }


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str, db: Session = Depends(get_db)):
    """Get a single policy (read-only)."""
    policy = (
        db.query(Policy)
        .options(joinedload(Policy.versions).joinedload(PolicyVersion.rules))
        .filter(Policy.policy_id == uuid.UUID(policy_id))
        .first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return _policy_to_response(policy)


@router.get("/policies/{policy_id}/assignments")
async def list_assignments(policy_id: str, db: Session = Depends(get_db)):
    """List all assignments for a policy (read-only)."""
    assignments = (
        db.query(PolicyAssignment)
        .filter(PolicyAssignment.policy_id == uuid.UUID(policy_id))
        .order_by(PolicyAssignment.created_at.desc())
        .all()
    )
    return {
        "policy_id": policy_id,
        "assignments": [
            {
                "assignment_id": str(a.assignment_id),
                "scope_type": a.scope_type,
                "scope_id": str(a.scope_id) if a.scope_id else None,
                "action_pattern": a.action_pattern,
                "priority_override": a.priority_override,
                "is_active": a.is_active,
                "valid_from": a.valid_from.isoformat() if a.valid_from else None,
                "valid_until": a.valid_until.isoformat() if a.valid_until else None,
            }
            for a in assignments
        ],
    }


# =====================================================================
# DECISION LOG (audit — read-only)
# =====================================================================

@router.get("/policy-decisions")
async def list_decisions(
    tenant_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List policy decision logs (audit trail) with filters."""
    q = db.query(PolicyDecisionLog)
    if tenant_id:
        q = q.filter(PolicyDecisionLog.tenant_id == uuid.UUID(tenant_id))
    if action:
        q = q.filter(PolicyDecisionLog.action == action)
    if user_id:
        q = q.filter(PolicyDecisionLog.user_id == uuid.UUID(user_id))
    if decision:
        q = q.filter(PolicyDecisionLog.decision == decision)

    total = q.count()
    logs = q.order_by(PolicyDecisionLog.evaluated_at.desc()).offset(skip).limit(limit).all()

    return {
        "decisions": [
            {
                "decision_id": str(log.decision_id),
                "tenant_id": str(log.tenant_id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "decision": log.decision,
                "reason": log.reason,
                "matched_policies": log.matched_policies,
                "evaluation_ms": log.evaluation_ms,
                "correlation_id": log.correlation_id,
                "evaluated_at": log.evaluated_at.isoformat(),
            }
            for log in logs
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }
