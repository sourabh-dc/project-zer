"""
budget_change_request_routes.py
--------------------------------
Top-up, bring-forward, and reallocation requests that require approval.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    BudgetChangeRequest, CostCentreBudgetVersion, BudgetTransaction,
)
from provisioning_service.Schemas import BringForwardRequest, BudgetReallocationRequest, BudgetChangeDecision
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/budget-change-requests", tags=["Budget Change Requests"])


# =============================================================================
# BRING FORWARD
# =============================================================================

@router.post("/bring-forward", status_code=201)
async def request_bring_forward(
    req: BringForwardRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.request")),
):
    """
    Request to pull future-period budget into the current period.
    Routes to cost-centre manager / SLT for approval.
    """
    tenant_id    = _tid(ctx)
    requester_id = _uid(ctx)

    from_v = _get_version_or_404(db, req.from_version_id, tenant_id)
    to_v   = _get_version_or_404(db, req.to_version_id, tenant_id)

    # Validate annual ceiling won't be breached (combined budget across both periods unchanged)
    available_in_from = from_v.budget_minor - from_v.committed_minor - from_v.spent_minor
    if available_in_from < req.amount_minor:
        raise HTTPException(
            400,
            f"Future period only has {available_in_from} available; cannot bring forward {req.amount_minor}"
        )

    change_req = BudgetChangeRequest(
        change_req_id=uuid.uuid4(),
        tenant_id=tenant_id,
        request_type="bring_forward",
        requester_id=requester_id,
        cost_centre_id=uuid.UUID(req.cost_centre_id),
        from_version_id=uuid.UUID(req.from_version_id),
        to_version_id=uuid.UUID(req.to_version_id),
        amount_minor=req.amount_minor,
        currency=from_v.currency,
        justification=req.justification,
        status="pending",
    )
    db.add(change_req)
    db.commit()
    db.refresh(change_req)

    _outbox(db, tenant_id, "budget_change_request.bring_forward.submitted",
            {"change_req_id": str(change_req.change_req_id),
             "amount_minor": req.amount_minor, "justification": req.justification})

    return _change_req_dict(change_req)


# =============================================================================
# TOP-UP (additive)
# =============================================================================

@router.post("/top-up", status_code=201)
async def request_top_up(
    cost_centre_id: str,
    to_version_id: str,
    amount_minor: int,
    justification: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.request")),
):
    """Request additional budget for a CC period from the central pool."""
    tenant_id    = _tid(ctx)
    requester_id = _uid(ctx)

    to_v = _get_version_or_404(db, to_version_id, tenant_id)

    change_req = BudgetChangeRequest(
        change_req_id=uuid.uuid4(),
        tenant_id=tenant_id,
        request_type="top_up",
        requester_id=requester_id,
        cost_centre_id=uuid.UUID(cost_centre_id),
        from_version_id=None,
        to_version_id=uuid.UUID(to_version_id),
        amount_minor=amount_minor,
        currency=to_v.currency,
        justification=justification,
        status="pending",
    )
    db.add(change_req)
    db.commit()
    db.refresh(change_req)

    _outbox(db, tenant_id, "budget_change_request.top_up.submitted",
            {"change_req_id": str(change_req.change_req_id), "amount_minor": amount_minor})

    return _change_req_dict(change_req)


# =============================================================================
# REALLOCATION REQUEST
# =============================================================================

@router.post("/reallocation", status_code=201)
async def request_reallocation(
    req: BudgetReallocationRequest,
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.request")),
):
    """Request a transfer of budget from one CC version to another."""
    tenant_id    = _tid(ctx)
    requester_id = _uid(ctx)

    to_v = _get_version_or_404(db, req.target_version_id, tenant_id)

    change_req = BudgetChangeRequest(
        change_req_id=uuid.uuid4(),
        tenant_id=tenant_id,
        request_type="reallocation",
        requester_id=requester_id,
        cost_centre_id=uuid.UUID(cost_centre_id),
        from_version_id=uuid.UUID(req.source_version_id) if req.source_version_id else None,
        to_version_id=uuid.UUID(req.target_version_id),
        amount_minor=req.amount_minor,
        currency=to_v.currency,
        justification=req.note or "",
        status="pending",
    )
    db.add(change_req)
    db.commit()
    db.refresh(change_req)

    _outbox(db, tenant_id, "budget_change_request.reallocation.submitted",
            {"change_req_id": str(change_req.change_req_id), "amount_minor": req.amount_minor})

    return _change_req_dict(change_req)


# =============================================================================
# LIST & DECISION
# =============================================================================

@router.get("")
async def list_change_requests(
    status: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    request_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(BudgetChangeRequest).filter(BudgetChangeRequest.tenant_id == tenant_id)
    if status:
        q = q.filter(BudgetChangeRequest.status == status)
    if cost_centre_id:
        q = q.filter(BudgetChangeRequest.cost_centre_id == uuid.UUID(cost_centre_id))
    if request_type:
        q = q.filter(BudgetChangeRequest.request_type == request_type)
    total = q.count()
    rows  = q.order_by(BudgetChangeRequest.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "requests": [_change_req_dict(r) for r in rows]}


@router.post("/{change_req_id}/decide")
async def decide_change_request(
    change_req_id: str,
    req: BudgetChangeDecision,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    """
    Approve or reject a budget change request.
    On approval the underlying budget versions are updated and a ledger entry is written.
    """
    tenant_id  = _tid(ctx)
    approver_id = _uid(ctx)

    try:
        cid = uuid.UUID(change_req_id)
    except ValueError:
        raise HTTPException(400, "Invalid change_req_id")

    cr = db.query(BudgetChangeRequest).filter(
        BudgetChangeRequest.change_req_id == cid,
        BudgetChangeRequest.tenant_id == tenant_id,
    ).first()
    if not cr:
        raise HTTPException(404, "Budget change request not found")
    if cr.status != "pending":
        raise HTTPException(400, f"Request is already in status '{cr.status}'")

    now = datetime.now(timezone.utc)
    cr.status      = req.decision
    cr.approved_by = approver_id
    cr.approved_at = now
    if req.decision == "rejected":
        cr.rejection_reason = req.note
    cr.updated_at = now

    if req.decision == "approved":
        _apply_budget_change(db, cr, tenant_id, approver_id)

    db.commit()

    _outbox(db, tenant_id, f"budget_change_request.{req.decision}",
            {"change_req_id": change_req_id, "approved_by": str(approver_id)})

    return _change_req_dict(cr)


# =============================================================================
# Internal helpers
# =============================================================================

def _apply_budget_change(db: Session, cr: BudgetChangeRequest, tenant_id, approver_id):
    """Execute the approved budget change on the relevant CC budget versions."""
    to_v = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.version_id == cr.to_version_id
    ).first()
    if not to_v:
        return

    if cr.request_type in ("bring_forward", "reallocation") and cr.from_version_id:
        from_v = db.query(CostCentreBudgetVersion).filter(
            CostCentreBudgetVersion.version_id == cr.from_version_id
        ).first()
        if from_v:
            from_v.budget_minor -= cr.amount_minor
            db.add(BudgetTransaction(
                txn_id=uuid.uuid4(),
                tenant_id=tenant_id,
                txn_type="reallocation_debit" if cr.request_type == "reallocation" else "bring_forward",
                source_version_id=from_v.version_id,
                target_version_id=to_v.version_id,
                amount_minor=cr.amount_minor,
                currency=cr.currency,
                reference_id=cr.change_req_id,
                performed_by=approver_id,
                note=cr.justification,
            ))

    to_v.budget_minor += cr.amount_minor
    db.add(BudgetTransaction(
        txn_id=uuid.uuid4(),
        tenant_id=tenant_id,
        txn_type="reallocation_credit" if cr.request_type == "reallocation" else cr.request_type,
        source_version_id=cr.from_version_id,
        target_version_id=to_v.version_id,
        amount_minor=cr.amount_minor,
        currency=cr.currency,
        reference_id=cr.change_req_id,
        performed_by=approver_id,
        note=cr.justification,
    ))
    db.flush()


def _tid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))


def _uid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))


def _get_version_or_404(db, version_id: str, tenant_id: uuid.UUID):
    try:
        vid = uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(400, "Invalid version_id")
    v = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.version_id == vid,
        CostCentreBudgetVersion.tenant_id == tenant_id,
    ).first()
    if not v:
        raise HTTPException(404, "CC budget version not found")
    return v


def _outbox(db, tenant_id, event_type, data):
    try:
        create_outbox_event(db, tenant_id, event_type, data)
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for {event_type}: {e}")


def _change_req_dict(cr):
    return {
        "change_req_id": str(cr.change_req_id),
        "request_type": cr.request_type,
        "cost_centre_id": str(cr.cost_centre_id),
        "from_version_id": str(cr.from_version_id) if cr.from_version_id else None,
        "to_version_id": str(cr.to_version_id),
        "amount_minor": cr.amount_minor,
        "currency": cr.currency,
        "justification": cr.justification,
        "status": cr.status,
        "approved_by": str(cr.approved_by) if cr.approved_by else None,
        "approved_at": cr.approved_at.isoformat() if cr.approved_at else None,
        "rejection_reason": cr.rejection_reason,
        "created_at": cr.created_at.isoformat() if cr.created_at else None,
    }

