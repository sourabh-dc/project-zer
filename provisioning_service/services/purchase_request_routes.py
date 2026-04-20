"""
purchase_request_routes.py
--------------------------
Submit purchase requests, check budget headroom, manage approval workflows.

Policy gates
------------
All access-control and budget decisions are delegated to OPA via
require_policy().  Resource context is computed by resource_loaders.py
and passed as enriched dicts to the policy engine:

  purchase_request.create  — budget headroom, blocked flag, self-approve flag
  purchase_request.decide  — SOX SoD (requester ≠ approver), task ownership
  purchase_request.issue_po — basic RBAC
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    PurchaseRequest, ApprovalWorkflow, ApprovalTask,
    ApprovalPolicy, CostCentre, User,
)
from provisioning_service.Schemas import PurchaseRequestCreate, ApprovalDecisionRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.approval_engine import resolve_workflow, advance_workflow
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.core.helpers.resource_loaders import (
    purchase_request_create_resource,
    purchase_request_decide_resource,
)
from provisioning_service.core.period_calculator import get_current_period
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/purchase-requests", tags=["Purchase Requests"])


# =============================================================================
# SUBMIT A PURCHASE REQUEST
# =============================================================================

@router.post("", status_code=201)
async def submit_purchase_request(
    req: PurchaseRequestCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.place")),
    # Resource loader computes budget headroom once; DI cache reuses it in
    # both the budget_ctx binding below and inside require_policy.
    budget_ctx: dict = Depends(purchase_request_create_resource),
    policy_result: dict = Depends(
        require_policy(
            "purchase_request.create",
            resource_loader=purchase_request_create_resource,
            # OPA returns "require_approval" when the request needs a workflow;
            # we must not raise here — the route handles routing instead.
            pass_on_require_approval=True,
        )
    ),
):
    """
    Submit a purchase request.

    OPA handles:
      - deny  → budget blocked (CC insufficient / company hard cap)
      - deny  → cross-tenant / no subscription
      - allow → can_self_approve (auto-approve path)
      - require_approval → needs workflow (user window limits breached)
    """
    tenant_id    = _tid(ctx)
    requester_id = _uid(ctx)

    cc = db.query(CostCentre).filter(
        CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id),
        CostCentre.tenant_id == tenant_id,
        CostCentre.is_active == True,
    ).first()
    if not cc:
        raise HTTPException(404, "Cost centre not found")

    # Period resolved by the resource loader — reuse from budget_ctx.
    current_period = get_current_period(db, tenant_id)
    year_id   = current_period.year_id   if current_period else None
    period_id = current_period.period_id if current_period else None

    # Build reference number
    count = db.query(PurchaseRequest).filter(
        PurchaseRequest.tenant_id == tenant_id
    ).count()
    ref_number = f"PR-{count + 1:06d}"

    purchase_req = PurchaseRequest(
        request_id=uuid.uuid4(),
        tenant_id=tenant_id,
        requester_id=requester_id,
        cost_centre_id=uuid.UUID(req.cost_centre_id),
        vendor_id=uuid.UUID(req.vendor_id) if req.vendor_id else None,
        category_id=uuid.UUID(req.category_id) if req.category_id else None,
        year_id=year_id,
        period_id=period_id,
        reference_number=ref_number,
        description=req.description,
        line_items=req.line_items,
        amount_minor=req.amount_minor,
        currency=req.currency,
        notes=req.notes,
        status="pending_approval",
    )
    db.add(purchase_req)
    db.flush()

    # OPA decision drives the self-approve vs workflow branch.
    opa_decision = policy_result.get("decision", "allow")

    if opa_decision == "allow":
        # Self-approve: all window limits within range.
        purchase_req.status      = "approved"
        purchase_req.approval_mode = "self_approved"
        purchase_req.approved_by = requester_id
        purchase_req.approved_at = datetime.now(timezone.utc)
        db.commit()

        try:
            create_outbox_event(db, tenant_id, "purchase_request.auto_approved",
                                {"request_id": str(purchase_req.request_id),
                                 "amount_minor": req.amount_minor,
                                 "reference_number": ref_number})
            db.commit()
        except Exception as e:
            logger.warning(f"Outbox failed: {e}")

        return _request_dict(purchase_req)

    # require_approval: route through an approval workflow.
    approval_policy = _resolve_policy(db, tenant_id, uuid.UUID(req.cost_centre_id))
    if not approval_policy:
        raise HTTPException(
            422,
            "No active approval policy found for this cost centre. "
            "Please configure an approval policy before submitting requests."
        )

    purchase_req.approval_mode = "workflow"
    workflow = resolve_workflow(db, purchase_req, approval_policy)
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "purchase_request.submitted",
                            {"request_id": str(purchase_req.request_id),
                             "workflow_id": str(workflow.workflow_id),
                             "amount_minor": req.amount_minor})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed: {e}")

    return _request_dict(purchase_req)


# =============================================================================
# LIST & GET
# =============================================================================

@router.get("")
async def list_purchase_requests(
    status: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    requester_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.view")),
):
    tenant_id = _tid(ctx)
    q = db.query(PurchaseRequest).filter(PurchaseRequest.tenant_id == tenant_id)
    if status:
        q = q.filter(PurchaseRequest.status == status)
    if cost_centre_id:
        q = q.filter(PurchaseRequest.cost_centre_id == uuid.UUID(cost_centre_id))
    if requester_id:
        q = q.filter(PurchaseRequest.requester_id == uuid.UUID(requester_id))
    total = q.count()
    rows  = q.order_by(PurchaseRequest.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "requests": [_request_dict(r) for r in rows]}


@router.get("/my-tasks")
async def my_pending_tasks(
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.approve")),
):
    """Return all pending approval tasks assigned to the calling user."""
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    tasks = (
        db.query(ApprovalTask)
        .filter(
            ApprovalTask.tenant_id == tenant_id,
            ApprovalTask.assignee_user_id == user_id,
            ApprovalTask.status == "pending",
        )
        .order_by(ApprovalTask.created_at)
        .all()
    )

    result = []
    for task in tasks:
        workflow = db.query(ApprovalWorkflow).filter(
            ApprovalWorkflow.workflow_id == task.workflow_id
        ).first()
        pr = db.query(PurchaseRequest).filter(
            PurchaseRequest.request_id == workflow.request_id
        ).first() if workflow else None
        result.append({
            "task_id": str(task.task_id),
            "stage_order": task.stage_order,
            "request": _request_dict(pr) if pr else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        })
    return {"pending_tasks": result}


@router.get("/{request_id}")
async def get_purchase_request(
    request_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.view")),
):
    tenant_id = _tid(ctx)
    pr = _get_pr_or_404(db, request_id, tenant_id)

    workflow = db.query(ApprovalWorkflow).filter(
        ApprovalWorkflow.request_id == pr.request_id
    ).first()

    tasks = []
    if workflow:
        tasks = db.query(ApprovalTask).filter(
            ApprovalTask.workflow_id == workflow.workflow_id
        ).order_by(ApprovalTask.stage_order, ApprovalTask.created_at).all()

    return {
        **_request_dict(pr),
        "workflow": {
            "workflow_id":         str(workflow.workflow_id) if workflow else None,
            "status":              workflow.status if workflow else None,
            "current_stage_order": workflow.current_stage_order if workflow else None,
        } if workflow else None,
        "tasks": [
            {
                "task_id":          str(t.task_id),
                "stage_order":      t.stage_order,
                "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
                "status":           t.status,
                "decided_at":       t.decided_at.isoformat() if t.decided_at else None,
                "note":             t.note,
            }
            for t in tasks
        ],
    }


# =============================================================================
# APPROVAL DECISION
# =============================================================================

@router.post("/tasks/{task_id}/decide")
async def decide_task(
    task_id: str,
    req: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.approve")),
    # OPA: checks SOX SoD (requester ≠ decider) + RBAC.
    # resource_loader pre-fetches task→workflow→request→policy from DB.
    # DI cache means the same queries are not repeated in advance_workflow's
    # own lookups (which are independent; duplication is intentional for
    # decoupling advance_workflow from the API layer).
    policy_result: dict = Depends(
        require_policy(
            "purchase_request.decide",
            resource_loader=purchase_request_decide_resource,
        )
    ),
):
    """
    Approve, reject, or escalate an approval task.
    SOX SoD is enforced by OPA before this handler is reached.
    """
    tenant_id  = _tid(ctx)
    decided_by = _uid(ctx)

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, "Invalid task_id")

    task = db.query(ApprovalTask).filter(
        ApprovalTask.task_id == tid,
        ApprovalTask.tenant_id == tenant_id,
    ).first()
    if not task:
        raise HTTPException(404, "Approval task not found")

    try:
        result = advance_workflow(
            db,
            task_id=tid,
            decision=req.decision,
            decided_by_id=decided_by,
            note=req.note,
        )
    except ValueError as ve:
        raise HTTPException(422, str(ve))

    db.commit()

    workflow = db.query(ApprovalWorkflow).filter(
        ApprovalWorkflow.workflow_id == task.workflow_id
    ).first()
    try:
        create_outbox_event(db, tenant_id, f"approval_task.{result['status']}",
                            {"task_id": task_id, "decided_by": str(decided_by),
                             "workflow_id": str(workflow.workflow_id) if workflow else None,
                             "result": result})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed: {e}")

    return result


@router.post("/{request_id}/issue-po")
async def issue_po(
    request_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.manage")),
    policy_result: dict = Depends(
        require_policy("purchase_request.issue_po", resource_from="none")
    ),
):
    """Mark an approved request as PO issued."""
    tenant_id = _tid(ctx)
    pr = _get_pr_or_404(db, request_id, tenant_id)

    if pr.status != "approved":
        raise HTTPException(400, f"Request is in status '{pr.status}'; must be 'approved' to issue PO")

    pr.status      = "po_issued"
    pr.po_issued_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "purchase_request.po_issued",
                            {"request_id": request_id, "amount_minor": pr.amount_minor,
                             "vendor_id": str(pr.vendor_id) if pr.vendor_id else None,
                             "reference_number": pr.reference_number})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed: {e}")

    return {"request_id": request_id, "status": "po_issued",
            "po_issued_at": pr.po_issued_at.isoformat()}


# =============================================================================
# Internal helpers
# =============================================================================

def _tid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))


def _uid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))


def _get_pr_or_404(db, request_id, tenant_id):
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request_id")
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.request_id == rid,
        PurchaseRequest.tenant_id == tenant_id,
    ).first()
    if not pr:
        raise HTTPException(404, "Purchase request not found")
    return pr


def _resolve_policy(db, tenant_id: uuid.UUID, cost_centre_id: uuid.UUID):
    """Find the most specific active policy: CC-level first, then tenant-wide."""
    policy = db.query(ApprovalPolicy).filter(
        ApprovalPolicy.tenant_id == tenant_id,
        ApprovalPolicy.cost_centre_id == cost_centre_id,
        ApprovalPolicy.is_active == True,
    ).first()
    if policy:
        return policy
    return db.query(ApprovalPolicy).filter(
        ApprovalPolicy.tenant_id == tenant_id,
        ApprovalPolicy.cost_centre_id.is_(None),
        ApprovalPolicy.is_active == True,
    ).first()


def _request_dict(pr):
    if not pr:
        return None
    return {
        "request_id":       str(pr.request_id),
        "tenant_id":        str(pr.tenant_id),
        "requester_id":     str(pr.requester_id),
        "cost_centre_id":   str(pr.cost_centre_id),
        "vendor_id":        str(pr.vendor_id) if pr.vendor_id else None,
        "category_id":      str(pr.category_id) if pr.category_id else None,
        "reference_number": pr.reference_number,
        "description":      pr.description,
        "amount_minor":     pr.amount_minor,
        "currency":         pr.currency,
        "status":           pr.status,
        "approval_mode":    pr.approval_mode,
        "approved_by":      str(pr.approved_by) if pr.approved_by else None,
        "approved_at":      pr.approved_at.isoformat() if pr.approved_at else None,
        "po_issued_at":     pr.po_issued_at.isoformat() if pr.po_issued_at else None,
        "po_reference":     pr.po_reference,
        "created_at":       pr.created_at.isoformat() if pr.created_at else None,
    }
