"""
approval_policy_routes.py
-------------------------
CRUD for approval policies, stages, stage conditions, and stage approvers.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    ApprovalPolicy, ApprovalStage, ApprovalStageCondition, ApprovalStageApprover,
)
from provisioning_service.Schemas import ApprovalPolicyCreate
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/approval-policies", tags=["Approval Policies"])


@router.post("", status_code=201)
async def create_policy(
    req: ApprovalPolicyCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    policy=Depends(require_policy("approval_policy.create")),
):
    """
    Create an N-level approval policy with stages, conditions, and approver specs.
    """
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    policy = ApprovalPolicy(
        policy_id=uuid.uuid4(),
        tenant_id=tenant_id,
        cost_centre_id=uuid.UUID(req.cost_centre_id) if req.cost_centre_id else None,
        name=req.name,
        description=req.description,
        routing_mode=req.routing_mode,
        broadcast_n=req.broadcast_n,
        sox_sod_enforced=req.sox_sod_enforced,
        partial_approval_mode=req.partial_approval_mode,
        zero_value_mode=req.zero_value_mode,
        is_active=True,
        created_by=user_id,
    )
    db.add(policy)
    db.flush()

    for stage_req in sorted(req.stages, key=lambda s: s.stage_order):
        stage = ApprovalStage(
            stage_id=uuid.uuid4(),
            policy_id=policy.policy_id,
            stage_order=stage_req.stage_order,
            name=stage_req.name,
            parallel_allowed=stage_req.parallel_allowed,
            min_approvers=stage_req.min_approvers,
            escalation_timeout_hours=stage_req.escalation_timeout_hours,
        )
        db.add(stage)
        db.flush()

        for cond_req in stage_req.conditions:
            db.add(ApprovalStageCondition(
                condition_id=uuid.uuid4(),
                stage_id=stage.stage_id,
                field=cond_req.field,
                operator=cond_req.operator,
                value=cond_req.value,
                logic=cond_req.logic,
            ))

        for approver_req in stage_req.approvers:
            db.add(ApprovalStageApprover(
                id=uuid.uuid4(),
                stage_id=stage.stage_id,
                approver_type=approver_req.approver_type,
                approver_user_id=uuid.UUID(approver_req.approver_user_id) if approver_req.approver_user_id else None,
                org_unit_id=uuid.UUID(approver_req.org_unit_id) if approver_req.org_unit_id else None,
                role_code=approver_req.role_code,
            ))

    db.commit()
    db.refresh(policy)

    try:
        create_outbox_event(db, tenant_id, "approval_policy.created",
                            {"policy_id": str(policy.policy_id), "name": policy.name,
                             "stage_count": len(req.stages)})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for approval_policy.created: {e}")

    return _policy_dict(db, policy)


@router.get("")
async def list_policies(
    cost_centre_id: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(ApprovalPolicy).filter(ApprovalPolicy.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ApprovalPolicy.is_active == True)
    if cost_centre_id:
        q = q.filter(ApprovalPolicy.cost_centre_id == uuid.UUID(cost_centre_id))
    return {"policies": [_policy_dict(db, p) for p in q.order_by(ApprovalPolicy.name).all()]}


@router.get("/{policy_id}")
async def get_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    policy = _get_policy_or_404(db, policy_id, tenant_id)
    return _policy_dict(db, policy)


@router.delete("/{policy_id}", status_code=204)
async def deactivate_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    policy=Depends(require_policy("approval_policy.delete", resource_from="none")),
):
    tenant_id = _tid(ctx)
    policy = _get_policy_or_404(db, policy_id, tenant_id)
    policy.is_active = False
    policy.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "approval_policy.deactivated", {"policy_id": policy_id})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed: {e}")


# =============================================================================
# Internal helpers
# =============================================================================

def _tid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))


def _uid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))


def _get_policy_or_404(db, policy_id, tenant_id):
    try:
        pid = uuid.UUID(policy_id)
    except ValueError:
        raise HTTPException(400, "Invalid policy_id")
    p = db.query(ApprovalPolicy).filter(
        ApprovalPolicy.policy_id == pid, ApprovalPolicy.tenant_id == tenant_id
    ).first()
    if not p:
        raise HTTPException(404, "Approval policy not found")
    return p


def _policy_dict(db, policy):
    stages = (
        db.query(ApprovalStage)
        .filter(ApprovalStage.policy_id == policy.policy_id)
        .order_by(ApprovalStage.stage_order)
        .all()
    )
    return {
        "policy_id": str(policy.policy_id),
        "name": policy.name,
        "description": policy.description,
        "routing_mode": policy.routing_mode,
        "broadcast_n": policy.broadcast_n,
        "sox_sod_enforced": policy.sox_sod_enforced,
        "partial_approval_mode": policy.partial_approval_mode,
        "zero_value_mode": policy.zero_value_mode,
        "cost_centre_id": str(policy.cost_centre_id) if policy.cost_centre_id else None,
        "is_active": policy.is_active,
        "stages": [
            {
                "stage_id": str(s.stage_id),
                "stage_order": s.stage_order,
                "name": s.name,
                "parallel_allowed": s.parallel_allowed,
                "min_approvers": s.min_approvers,
                "escalation_timeout_hours": s.escalation_timeout_hours,
                "conditions": [
                    {
                        "condition_id": str(c.condition_id),
                        "field": c.field,
                        "operator": c.operator,
                        "value": c.value,
                        "logic": c.logic,
                    }
                    for c in s.conditions
                ],
                "approvers": [
                    {
                        "id": str(a.id),
                        "approver_type": a.approver_type,
                        "approver_user_id": str(a.approver_user_id) if a.approver_user_id else None,
                        "org_unit_id": str(a.org_unit_id) if a.org_unit_id else None,
                        "role_code": a.role_code,
                    }
                    for a in s.approvers
                ],
            }
            for s in stages
        ],
    }

