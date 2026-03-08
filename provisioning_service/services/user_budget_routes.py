"""
user_budget_routes.py
---------------------
User-to-cost-centre assignments and per-user budget/approval limit windows.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    UserCostCentreAssignment, UserBudgetLimit, User, CostCentre,
    FinancialYear, FinancialPeriod,
)
from provisioning_service.Schemas import (
    UserCCAssignmentCreate, UserBudgetLimitCreate, UserBudgetLimitUpdate,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/user-budgets", tags=["User Budgets"])


# =============================================================================
# USER → COST CENTRE ASSIGNMENTS
# =============================================================================

@router.post("/assignments", status_code=201)
async def assign_user_to_cost_centre(
    req: UserCCAssignmentCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    _validate_user(db, req.user_id, tenant_id)
    _validate_cc(db, req.cost_centre_id, tenant_id)

    existing = db.query(UserCostCentreAssignment).filter(
        UserCostCentreAssignment.user_id == uuid.UUID(req.user_id),
        UserCostCentreAssignment.cost_centre_id == uuid.UUID(req.cost_centre_id),
        UserCostCentreAssignment.is_active == True,
    ).first()
    if existing:
        raise HTTPException(409, "User is already assigned to this cost centre")

    # If is_primary, unset other primary assignments for this user
    if req.is_primary:
        db.query(UserCostCentreAssignment).filter(
            UserCostCentreAssignment.user_id == uuid.UUID(req.user_id),
            UserCostCentreAssignment.is_primary == True,
        ).update({"is_primary": False})

    assignment = UserCostCentreAssignment(
        assignment_id=uuid.uuid4(),
        user_id=uuid.UUID(req.user_id),
        cost_centre_id=uuid.UUID(req.cost_centre_id),
        tenant_id=tenant_id,
        is_primary=req.is_primary,
        is_active=True,
        effective_from=req.effective_from,
        effective_to=req.effective_to,
        assigned_by=user_id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    _outbox(db, tenant_id, "user_cc_assignment.created",
            {"user_id": req.user_id, "cost_centre_id": req.cost_centre_id})

    return {
        "assignment_id": str(assignment.assignment_id),
        "user_id": req.user_id,
        "cost_centre_id": req.cost_centre_id,
        "is_primary": assignment.is_primary,
    }


@router.get("/assignments")
async def list_assignments(
    user_id: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(UserCostCentreAssignment).filter(
        UserCostCentreAssignment.tenant_id == tenant_id
    )
    if user_id:
        q = q.filter(UserCostCentreAssignment.user_id == uuid.UUID(user_id))
    if cost_centre_id:
        q = q.filter(UserCostCentreAssignment.cost_centre_id == uuid.UUID(cost_centre_id))
    if active_only:
        q = q.filter(UserCostCentreAssignment.is_active == True)
    rows = q.all()
    return {"assignments": [
        {
            "assignment_id": str(a.assignment_id),
            "user_id": str(a.user_id),
            "cost_centre_id": str(a.cost_centre_id),
            "is_primary": a.is_primary,
            "is_active": a.is_active,
            "effective_from": str(a.effective_from) if a.effective_from else None,
            "effective_to": str(a.effective_to) if a.effective_to else None,
        }
        for a in rows
    ]}


@router.delete("/assignments/{assignment_id}", status_code=204)
async def remove_assignment(
    assignment_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    try:
        aid = uuid.UUID(assignment_id)
    except ValueError:
        raise HTTPException(400, "Invalid assignment_id")
    a = db.query(UserCostCentreAssignment).filter(
        UserCostCentreAssignment.assignment_id == aid,
        UserCostCentreAssignment.tenant_id == tenant_id,
    ).first()
    if not a:
        raise HTTPException(404, "Assignment not found")
    a.is_active = False
    a.updated_at = datetime.now(timezone.utc)
    db.commit()
    _outbox(db, tenant_id, "user_cc_assignment.removed", {"assignment_id": assignment_id})


# =============================================================================
# USER BUDGET LIMITS
# =============================================================================

@router.post("/limits", status_code=201)
async def create_limit(
    req: UserBudgetLimitCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    _validate_user(db, req.user_id, tenant_id)
    _validate_cc(db, req.cost_centre_id, tenant_id)

    existing = db.query(UserBudgetLimit).filter(
        UserBudgetLimit.user_id == uuid.UUID(req.user_id),
        UserBudgetLimit.cost_centre_id == uuid.UUID(req.cost_centre_id),
        UserBudgetLimit.year_id == uuid.UUID(req.year_id),
        UserBudgetLimit.limit_type == req.limit_type,
        UserBudgetLimit.window_type == req.window_type,
        UserBudgetLimit.is_active == True,
    ).first()
    if existing:
        raise HTTPException(
            409,
            f"A {req.limit_type}/{req.window_type} limit already exists for this user/CC/year"
        )

    limit = UserBudgetLimit(
        limit_id=uuid.uuid4(),
        user_id=uuid.UUID(req.user_id),
        cost_centre_id=uuid.UUID(req.cost_centre_id),
        year_id=uuid.UUID(req.year_id),
        period_id=uuid.UUID(req.period_id) if req.period_id else None,
        tenant_id=tenant_id,
        currency="GBP",
        limit_type=req.limit_type,
        window_type=req.window_type,
        limit_amount_minor=req.limit_amount_minor,
        carry_forward_enabled=req.carry_forward_enabled,
        window_start=req.window_start,
        window_end=req.window_end,
        is_active=True,
        created_by=user_id,
    )
    db.add(limit)
    db.commit()
    db.refresh(limit)

    _outbox(db, tenant_id, "user_budget_limit.created",
            {"limit_id": str(limit.limit_id), "user_id": req.user_id,
             "limit_type": req.limit_type, "window_type": req.window_type,
             "limit_amount_minor": req.limit_amount_minor})

    return _limit_dict(limit)


@router.get("/limits")
async def list_limits(
    user_id: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    year_id: Optional[str] = Query(None),
    limit_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(UserBudgetLimit).filter(
        UserBudgetLimit.tenant_id == tenant_id,
        UserBudgetLimit.is_active == True,
    )
    if user_id:
        q = q.filter(UserBudgetLimit.user_id == uuid.UUID(user_id))
    if cost_centre_id:
        q = q.filter(UserBudgetLimit.cost_centre_id == uuid.UUID(cost_centre_id))
    if year_id:
        q = q.filter(UserBudgetLimit.year_id == uuid.UUID(year_id))
    if limit_type:
        q = q.filter(UserBudgetLimit.limit_type == limit_type)
    rows = q.all()
    return {"limits": [_limit_dict(l) for l in rows]}


@router.get("/limits/summary/{user_id}")
async def get_user_limit_summary(
    user_id: str,
    cost_centre_id: Optional[str] = Query(None),
    year_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    """Return aggregated budget summary for a user across all cost centres (or one)."""
    tenant_id = _tid(ctx)
    q = db.query(UserBudgetLimit).filter(
        UserBudgetLimit.user_id == uuid.UUID(user_id),
        UserBudgetLimit.tenant_id == tenant_id,
        UserBudgetLimit.is_active == True,
    )
    if cost_centre_id:
        q = q.filter(UserBudgetLimit.cost_centre_id == uuid.UUID(cost_centre_id))
    if year_id:
        q = q.filter(UserBudgetLimit.year_id == uuid.UUID(year_id))

    limits = q.all()
    return {
        "user_id": user_id,
        "limit_count": len(limits),
        "limits": [_limit_dict(l) for l in limits],
    }


@router.put("/limits/{limit_id}")
async def update_limit(
    limit_id: str,
    req: UserBudgetLimitUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    lim = _get_limit_or_404(db, limit_id, tenant_id)

    if req.limit_amount_minor is not None:
        lim.limit_amount_minor = req.limit_amount_minor
    if req.carry_forward_enabled is not None:
        lim.carry_forward_enabled = req.carry_forward_enabled
    if req.window_start is not None:
        lim.window_start = req.window_start
    if req.window_end is not None:
        lim.window_end = req.window_end
    if req.is_active is not None:
        lim.is_active = req.is_active

    lim.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lim)

    _outbox(db, tenant_id, "user_budget_limit.updated",
            {"limit_id": limit_id, "limit_amount_minor": lim.limit_amount_minor})

    return _limit_dict(lim)


@router.delete("/limits/{limit_id}", status_code=204)
async def deactivate_limit(
    limit_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    lim = _get_limit_or_404(db, limit_id, tenant_id)
    lim.is_active = False
    lim.updated_at = datetime.now(timezone.utc)
    db.commit()
    _outbox(db, tenant_id, "user_budget_limit.deactivated", {"limit_id": limit_id})


# =============================================================================
# Internal helpers
# =============================================================================

def _tid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))


def _uid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))


def _validate_user(db, user_id: str, tenant_id: uuid.UUID):
    u = db.query(User).filter(
        User.user_id == uuid.UUID(user_id), User.tenant_id == tenant_id
    ).first()
    if not u:
        raise HTTPException(404, "User not found")


def _validate_cc(db, cc_id: str, tenant_id: uuid.UUID):
    cc = db.query(CostCentre).filter(
        CostCentre.cost_centre_id == uuid.UUID(cc_id),
        CostCentre.tenant_id == tenant_id,
        CostCentre.is_active == True,
    ).first()
    if not cc:
        raise HTTPException(404, "Cost centre not found")


def _get_limit_or_404(db, limit_id: str, tenant_id: uuid.UUID):
    try:
        lid = uuid.UUID(limit_id)
    except ValueError:
        raise HTTPException(400, "Invalid limit_id")
    lim = db.query(UserBudgetLimit).filter(
        UserBudgetLimit.limit_id == lid,
        UserBudgetLimit.tenant_id == tenant_id,
    ).first()
    if not lim:
        raise HTTPException(404, "User budget limit not found")
    return lim


def _outbox(db, tenant_id, event_type, data):
    try:
        create_outbox_event(db, tenant_id, event_type, data)
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for {event_type}: {e}")


def _limit_dict(l):
    carry = l.carry_forward_minor if l.carry_forward_enabled else 0
    available = l.limit_amount_minor + carry - (l.committed_minor or 0) - (l.spent_minor or 0)
    return {
        "limit_id": str(l.limit_id),
        "user_id": str(l.user_id),
        "cost_centre_id": str(l.cost_centre_id),
        "year_id": str(l.year_id),
        "period_id": str(l.period_id) if l.period_id else None,
        "limit_type": l.limit_type,
        "window_type": l.window_type,
        "limit_amount_minor": l.limit_amount_minor,
        "committed_minor": l.committed_minor or 0,
        "spent_minor": l.spent_minor or 0,
        "carry_forward_minor": carry,
        "available_minor": available,
        "carry_forward_enabled": l.carry_forward_enabled,
        "window_start": str(l.window_start) if l.window_start else None,
        "window_end": str(l.window_end) if l.window_end else None,
        "is_active": l.is_active,
    }

