import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from operations_service.Models import Tenant, User, ApprovalRequest, ApprovalRequestApprover, \
    UserCostCentre, SpendingEvent, ApproverLimit, CostCentre, ApprovalLog, UserRole, Role, OrgUnit, \
    ApprovalChain, ApprovalChainStep
from operations_service.Schemas import UserContext, ApprovalChainRequest, ApprovalChainStepRequest, ApprovalRequestRequest, \
    ApprovalResponseRequest, ApproverLimitRequest
from operations_service.core.db_config import get_db
from operations_service.core.permission_check_helpers import require_permission, resolve_approvers_for_step, check_tenant_access
from operations_service.utils.logger import logger
from operations_service.utils.metrics import req_total, req_duration


router = APIRouter(prefix="/approvals", tags=["Approvals"])

# ==================================================================================
# APPROVALS MANAGEMENT ENDPOINTS
# ==================================================================================

@router.post("/chains", status_code=201)
async def create_approval_chain(
        req: ApprovalChainRequest,
        db: Session = Depends(get_db)
):
    """Create a new approval chain"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_chain", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Create approval chain
        chain = ApprovalChain(
            chain_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            description=req.description,
            chain_type=req.chain_type,
            is_active=req.is_active
        )
        db.add(chain)
        db.commit()
        db.refresh(chain)

        req_total.labels(operation="create_approval_chain", status="success").inc()
        req_duration.labels(operation="create_approval_chain").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created approval chain: {chain.chain_id} ({chain.name})")

        return {
            "chain_id": str(chain.chain_id),
            "tenant_id": str(chain.tenant_id),
            "name": chain.name,
            "description": chain.description,
            "chain_type": chain.chain_type,
            "is_active": chain.is_active,
            "created_at": chain.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_chain", status="error").inc()
        logger.error(f"❌ Approval chain creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chains")
async def list_approval_chains(
        tenant_id: Optional[str] = Query(None),
        chain_type: Optional[str] = Query(None),
        is_active: Optional[bool] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List approval chains"""
    try:
        q = db.query(ApprovalChain)
        if tenant_id:
            q = q.filter(ApprovalChain.tenant_id == uuid.UUID(tenant_id))
        if chain_type:
            q = q.filter(ApprovalChain.chain_type == chain_type)
        if is_active is not None:
            q = q.filter(ApprovalChain.is_active == is_active)

        total = q.count()
        chains = q.order_by(ApprovalChain.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "chains": [
                {
                    "chain_id": str(c.chain_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "description": c.description,
                    "chain_type": c.chain_type,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat()
                }
                for c in chains
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List approval chains failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/chains/steps", status_code=201)
async def create_approval_chain_step(
        req: ApprovalChainStepRequest,
        db: Session = Depends(get_db)
):
    """Create a new approval chain step"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_chain_step", status="start").inc()

        # Verify chain exists
        chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_id == uuid.UUID(req.approval_chain_id)
        ).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")

        # Create step
        step = ApprovalChainStep(
            id=uuid.uuid4(),
            approval_chain_id=uuid.UUID(req.approval_chain_id),
            step_number=req.step_number,
            approver_role=req.approver_role,
            approver_scope=req.approver_scope,
            escalation_after_hours=req.escalation_after_hours,
            is_required=req.is_required
        )
        db.add(step)
        db.commit()
        db.refresh(step)

        req_total.labels(operation="create_chain_step", status="success").inc()
        req_duration.labels(operation="create_chain_step").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created approval chain step: {step.id}")

        return {
            "id": str(step.id),
            "approval_chain_id": str(step.approval_chain_id),
            "step_number": step.step_number,
            "approver_role": step.approver_role,
            "approver_scope": step.approver_scope,
            "escalation_after_hours": step.escalation_after_hours,
            "is_required": step.is_required,
            "created_at": step.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid approval chain ID format")
    except HTTPException:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_chain_step", status="error").inc()
        logger.error(f"❌ Chain step creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chains/{chain_id}/steps")
async def list_chain_steps(
        chain_id: str,
        db: Session = Depends(get_db)
):
    """List steps for an approval chain"""
    try:
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")

        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(chain_id)
        ).order_by(ApprovalChainStep.step_number).all()

        return {
            "chain_id": chain_id,
            "chain_name": chain.name,
            "steps": [
                {
                    "id": str(s.id),
                    "step_number": s.step_number,
                    "approver_role": s.approver_role,
                    "approver_scope": s.approver_scope,
                    "escalation_after_hours": s.escalation_after_hours,
                    "is_required": s.is_required,
                    "created_at": s.created_at.isoformat()
                }
                for s in steps
            ],
            "total": len(steps)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chain ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List chain steps failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Note: creation endpoint exists above as create_chain_step.
# Expose it with the expected route: POST /chains/{chain_id}/steps
@router.post("/chains/{chain_id}/steps", status_code=201)
async def create_chain_step_alias(
        chain_id: str,
        req: ApprovalChainStepRequest,
        db: Session = Depends(get_db)
):
    # inject chain id into request model
    req.approval_chain_id = chain_id
    return await create_approval_chain_step(req, db)


@router.post("/requests", status_code=201)
async def create_approval_request(
        req: ApprovalRequestRequest,
        current_user_id: str,
        db: Session = Depends(get_db),
):
    """
    Create a new approval request without chains/steps.
    Assign all eligible tenant_admin approvers for the tenant (org_unit scoped if provided).
    """
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_request", status="start").inc()

        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if req.org_unit_id:
            org_unit = db.query(OrgUnit).filter(
                OrgUnit.org_unit_id == uuid.UUID(req.org_unit_id),
                OrgUnit.tenant_id == uuid.UUID(req.tenant_id)
            ).first()
            if not org_unit:
                raise HTTPException(status_code=404, detail="Organizational unit not found or not accessible by tenant")

        request_number = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        approval_request_id = uuid.uuid4()
        approval_request = ApprovalRequest(
            request_id=approval_request_id,
            tenant_id=uuid.UUID(req.tenant_id),
            org_unit_id=uuid.UUID(req.org_unit_id) if req.org_unit_id else None,
            chain_id=None,  # chain concept removed; nullable
            request_number=request_number,
            request_type=req.request_type,
            request_data=req.request_data,
            requested_by=current_user_id,
            request_status="pending",
            current_step_number=1,
            total_amount_minor=req.total_amount_minor,
            remaining_amount_minor=req.total_amount_minor,
            currency=req.currency,
            due_date=req.due_date,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )
        db.add(approval_request)
        db.flush()

        # Eligible approvers: all tenant_admin in tenant (org_unit filter not enforced here; could be added)
        approver_user_ids = [
            ur.user_id for ur in db.query(UserRole).join(Role, Role.role_id == UserRole.role_id).filter(
                UserRole.tenant_id == uuid.UUID(req.tenant_id),
                Role.code == "tenant_admin"
            ).all()
        ]
        if not approver_user_ids:
            raise HTTPException(status_code=500, detail="No approvers found for tenant")

        for approver_user_id in approver_user_ids:
            db.add(ApprovalRequestApprover(
                id=uuid.uuid4(),
                request_id=approval_request.request_id,
                approver_user_id=approver_user_id,
                approver_role="tenant_admin",
                step_number=1,
                status="pending"
            ))

        db.add(ApprovalLog(
            request_id=approval_request.request_id,
            actor_id=uuid.UUID(current_user_id),
            action="created",
            amount_minor=approval_request.total_amount_minor,
            remaining_amount_minor=approval_request.remaining_amount_minor,
            comment="Approval request created"
        ))

        db.commit()
        db.refresh(approval_request)

        req_total.labels(operation="create_approval_request", status="success").inc()
        req_duration.labels(operation="create_approval_request").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created approval request: {approval_request.request_id}")

        return {
            "request_id": str(approval_request.request_id),
            "request_number": approval_request.request_number,
            "tenant_id": str(approval_request.tenant_id),
            "request_type": approval_request.request_type,
            "requested_by": str(approval_request.requested_by),
            "request_status": approval_request.request_status,
            "total_amount_minor": approval_request.total_amount_minor,
            "remaining_amount_minor": approval_request.remaining_amount_minor,
            "currency": approval_request.currency,
            "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
            "expires_at": approval_request.expires_at.isoformat() if approval_request.expires_at else None,
            "created_at": approval_request.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_request", status="error").inc()
        logger.error(f"❌ Approval request creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/requests")
async def list_approval_requests(
        tenant_id: Optional[str] = Query(None),
        request_type: Optional[str] = Query(None),
        request_status: Optional[str] = Query(None),
        requested_by: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List approval requests"""
    try:
        q = db.query(ApprovalRequest)
        if tenant_id:
            q = q.filter(ApprovalRequest.tenant_id == uuid.UUID(tenant_id))
        if request_type:
            q = q.filter(ApprovalRequest.request_type == request_type)
        if request_status:
            q = q.filter(ApprovalRequest.request_status == request_status)
        if requested_by:
            q = q.filter(ApprovalRequest.requested_by == uuid.UUID(requested_by))

        total = q.count()
        requests = q.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "requests": [
                {
                    "request_id": str(r.request_id),
                    "request_number": r.request_number,
                    "tenant_id": str(r.tenant_id),
                    "chain_id": str(r.chain_id),
                    "request_type": r.request_type,
                    "requested_by": str(r.requested_by),
                    "request_status": r.request_status,
                    "current_step_number": r.current_step_number,
                    "total_amount_minor": r.total_amount_minor,
                    "currency": r.currency,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "created_at": r.created_at.isoformat()
                }
                for r in requests
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List approval requests failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/requests/{request_id}")
async def get_approval_request(
        request_id: str,
        db: Session = Depends(get_db)
):
    """Get approval request details"""
    try:
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()

        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        # Get approvers
        approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()

        return {
            "request_id": str(request.request_id),
            "request_number": request.request_number,
            "tenant_id": str(request.tenant_id),
            "chain_id": str(request.chain_id),
            "request_type": request.request_type,
            "request_data": request.request_data,
            "requested_by": str(request.requested_by),
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "total_amount_minor": request.total_amount_minor,
            "currency": request.currency,
            "due_date": request.due_date.isoformat() if request.due_date else None,
            "completed_date": request.completed_date.isoformat() if request.completed_date else None,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None
                }
                for a in approvers
            ],
            "created_at": request.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get approval request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/requests/{request_id}/approvers")
async def get_request_approvers(
        request_id: str,
        db: Session = Depends(get_db)
):
    """Get all approvers for an approval request"""
    try:
        # Verify request exists
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()

        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        # Get approvers with user details
        approvers = db.query(ApprovalRequestApprover, User).join(
            User, ApprovalRequestApprover.approver_user_id == User.user_id
        ).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()

        return {
            "request_id": request_id,
            "request_number": request.request_number,
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_email": u.email,
                    "approver_name": u.display_name,
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None,
                    "escalation_sent": a.escalation_sent,
                    "created_at": a.created_at.isoformat()
                }
                for a, u in approvers
            ],
            "total": len(approvers)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get request approvers failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/requests/{request_id}/respond")
async def respond_to_approval_request(
        request_id: str,
        req: ApprovalResponseRequest,
        db: Session = Depends(get_db)
):
    """
    Respond to an approval request with approve/partial_approve/reject.
    - Uses row-level locking to avoid simultaneous approvals.
    - Updates remaining_amount, request status, approver limits (if present), and logs.
    - On approval (full/partial) credits user budget from cost centre if request_type is budget.
    """
    start = datetime.now()
    try:
        req_total.labels(operation="respond_approval", status="start").inc()

        # lock the request row
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).with_for_update().first()
        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        if approval_request.request_status not in ["pending", "partially_approved", "escalated"]:
            raise HTTPException(status_code=400, detail=f"Request not actionable (status: {approval_request.request_status})")

        # expiry check
        if approval_request.expires_at and datetime.now(timezone.utc) > approval_request.expires_at:
            approval_request.request_status = "expired"
            db.commit()
            raise HTTPException(status_code=400, detail="Request expired")

        approver = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id),
            ApprovalRequestApprover.status.in_(["pending", "approved"])  # allow same approver to respond again
        ).with_for_update().first()
        if not approver:
            raise HTTPException(status_code=404, detail="Approver assignment not found or already responded")

        remaining = approval_request.remaining_amount_minor or 0
        if remaining is None or remaining <= 0:
            raise HTTPException(status_code=400, detail="No remaining amount to approve")

        response = req.response.lower()
        approve_amount = req.approve_amount_minor
        if response == "approved" and approve_amount is None:
            approve_amount = remaining
        if response == "partial_approved":
            if approve_amount is None or approve_amount <= 0 or approve_amount >= remaining:
                raise HTTPException(status_code=400, detail="Invalid partial approve amount")
        if response == "rejected":
            approve_amount = 0

        # apply approval/rejection
        now_ts = datetime.now(timezone.utc)
        allocated_amount_minor = 0
        budget_allocated = False

        # approver limit enforcement (if defined)
        approver_limit = db.query(ApproverLimit).filter(
            ApproverLimit.approver_user_id == uuid.UUID(req.approver_user_id),
            ApproverLimit.tenant_id == approval_request.tenant_id
        ).with_for_update().first()
        if approver_limit:
            now = datetime.now(timezone.utc)
            reset = False
            if approver_limit.reset_period == "daily":
                reset = (not approver_limit.last_reset_at) or (approver_limit.last_reset_at.date() < now.date())
            elif approver_limit.reset_period == "weekly":
                reset = (not approver_limit.last_reset_at) or (approver_limit.last_reset_at.isocalendar()[1] != now.isocalendar()[1])
            elif approver_limit.reset_period == "monthly":
                reset = (not approver_limit.last_reset_at) or ((approver_limit.last_reset_at.year, approver_limit.last_reset_at.month) != (now.year, now.month))
            if reset:
                approver_limit.consumed_amount_minor = 0
                approver_limit.last_reset_at = now
            # org_unit match if specified
            if approver_limit.org_unit_id and approval_request.org_unit_id and approver_limit.org_unit_id != approval_request.org_unit_id:
                raise HTTPException(status_code=403, detail="Approver not eligible for this org unit")
            remaining_limit = (approver_limit.limit_amount_minor or 0) - (approver_limit.consumed_amount_minor or 0)
            if response in ["approved", "partial_approved"]:
                if approve_amount > remaining_limit:
                    raise HTTPException(status_code=400, detail="Approver limit exceeded")
                approver_limit.consumed_amount_minor += approve_amount

        # credit budget on approve/partial
        if response in ["approved", "partial_approved"] and approve_amount > 0:
            request_data = approval_request.request_data or {}
            user_id = request_data.get("user_id")
            amount_minor = approve_amount
            if approval_request.request_type.startswith("budget"):
                if not user_id:
                    raise HTTPException(status_code=400, detail="user_id required in request_data for budget approval")
                user_cc = db.query(UserCostCentre).filter(
                    UserCostCentre.user_id == uuid.UUID(user_id)
                ).with_for_update().first()
                if not user_cc:
                    raise HTTPException(status_code=404, detail="User cost centre assignment not found")
                # enforce CC budget >= sum allocations + new amount
                cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == user_cc.cost_centre_id).with_for_update().first()
                if not cc:
                    raise HTTPException(status_code=404, detail="Cost centre not found")
                total_alloc = db.query(func.coalesce(func.sum(UserCostCentre.allocated_budget_minor), 0)).filter(
                    UserCostCentre.cost_centre_id == user_cc.cost_centre_id
                ).scalar() or 0
                if total_alloc + amount_minor > cc.budget_minor:
                    raise HTTPException(status_code=400, detail="Cost centre budget exceeded")
                user_cc.allocated_budget_minor += amount_minor
                # spending event log
                spending_event = SpendingEvent(
                    event_id=uuid.uuid4(),
                    event_type="budget_allocated",
                    user_id=user_cc.user_id,
                    cost_centre_id=user_cc.cost_centre_id,
                    order_id=None,
                    approval_request_id=approval_request.request_id,
                    amount_minor=amount_minor,
                    currency_code=user_cc.currency_code,
                    event_metadata={
                        "request_number": approval_request.request_number,
                        "approved_by": req.approver_user_id
                    }
                )
                db.add(spending_event)
                budget_allocated = True
                allocated_amount_minor = amount_minor
            elif approval_request.request_type == "approval_limit_increase":
                target_user_id = request_data.get("approver_user_id")
                new_limit = request_data.get("new_limit_minor")
                reset_period = request_data.get("reset_period", "daily")
                if not target_user_id or not new_limit:
                    raise HTTPException(status_code=400, detail="approver_user_id and new_limit_minor required")
                limit_row = db.query(ApproverLimit).filter(
                    ApproverLimit.approver_user_id == uuid.UUID(target_user_id),
                    ApproverLimit.tenant_id == approval_request.tenant_id
                ).with_for_update().first()
                if not limit_row:
                    limit_row = ApproverLimit(
                        approver_user_id=uuid.UUID(target_user_id),
                        tenant_id=approval_request.tenant_id,
                        org_unit_id=approval_request.org_unit_id,
                        limit_amount_minor=new_limit,
                        consumed_amount_minor=0,
                        reset_period=reset_period,
                        last_reset_at=datetime.now(timezone.utc)
                    )
                    db.add(limit_row)
                else:
                    limit_row.limit_amount_minor = new_limit
                    limit_row.reset_period = reset_period
                budget_allocated = True
                allocated_amount_minor = 0
            elif approval_request.request_type == "cost_centre_increase":
                cc_id = request_data.get("cost_centre_id")
                add_amount = request_data.get("amount_minor")
                if not cc_id or not add_amount:
                    raise HTTPException(status_code=400, detail="cost_centre_id and amount_minor required")
                cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cc_id)).with_for_update().first()
                if not cc:
                    raise HTTPException(status_code=404, detail="Cost centre not found")
                cc.budget_minor += add_amount
                budget_allocated = True
                allocated_amount_minor = add_amount

        # update remaining and statuses (no step progression)
        new_remaining = remaining - (approve_amount or 0)
        approval_request.remaining_amount_minor = new_remaining
        approver.approved_amount_minor = approve_amount
        approver.responded_at = now_ts
        approver.notes = req.notes
        if response == "rejected":
            approver.status = "rejected"
            approval_request.request_status = "rejected"
            approval_request.completed_date = now_ts
        elif response == "partial_approved":
            approver.status = "approved"
            if new_remaining > 0:
                approval_request.request_status = "partially_approved"
            else:
                approval_request.request_status = "approved"
                approval_request.completed_date = now_ts
        else:  # approved full
            approver.status = "approved"
            approval_request.request_status = "approved"
            approval_request.completed_date = now_ts

        # If no pending approvers remain and still remaining_amount, close as closed_partially_approved
        pending_left = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == approval_request.request_id,
            ApprovalRequestApprover.status == "pending"
        ).count()
        if pending_left == 0 and approval_request.request_status == "partially_approved" and approval_request.remaining_amount_minor > 0:
            approval_request.request_status = "closed_partially_approved"
            approval_request.completed_date = now_ts

        # log immutable
        log_entry = ApprovalLog(
            id=uuid.uuid4(),
            request_id=approval_request.request_id,
            actor_id=uuid.UUID(req.approver_user_id),
            action=response,
            amount_minor=approve_amount,
            remaining_amount_minor=new_remaining,
            comment=req.notes
        )
        db.add(log_entry)

        db.commit()

        req_total.labels(operation="respond_approval", status="success").inc()
        req_duration.labels(operation="respond_approval").observe(
            (datetime.now() - start).total_seconds()
        )

        return {
            "request_id": str(approval_request.request_id),
            "request_status": approval_request.request_status,
            "remaining_amount_minor": approval_request.remaining_amount_minor,
            "approver_status": approver.status,
            "approved_amount_minor": approver.approved_amount_minor,
            "budget_allocated": budget_allocated,
            "allocated_amount_minor": allocated_amount_minor,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="respond_approval", status="error").inc()
        logger.error(f"❌ Respond to approval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/requests/{request_id}/escalate")
async def escalate_request(
        request_id: str,
        db: Session = Depends(get_db)
):
    """
    Manually escalate a pending/partially_approved request to director approvers.
    Creates director approver assignments if none exist.
    """
    req_total.labels(operation="escalate_approval", status="start").inc()
    try:
        approval_request = db.query(ApprovalRequest).filter(ApprovalRequest.request_id == uuid.UUID(request_id)).first()
        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        if approval_request.request_status not in ["pending", "partially_approved"]:
            raise HTTPException(status_code=400, detail="Request not eligible for escalation")

        directors = db.query(UserRole).join(Role, Role.role_id == UserRole.role_id).filter(
            UserRole.tenant_id == approval_request.tenant_id,
            Role.code == "director"
        ).all()
        if not directors:
            raise HTTPException(status_code=404, detail="No director role assignments found")

        existing = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == approval_request.request_id,
            ApprovalRequestApprover.approver_role == "director"
        ).all()
        if not existing:
            for dr in directors:
                db.add(ApprovalRequestApprover(
                    id=uuid.uuid4(),
                    request_id=approval_request.request_id,
                    approver_user_id=dr.user_id,
                    approver_role="director",
                    step_number=1,
                    status="pending"
                ))
        approval_request.request_status = "escalated"
        db.commit()
        req_total.labels(operation="escalate_approval", status="success").inc()
        return {"request_id": str(request_id), "status": approval_request.request_status}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="escalate_approval", status="error").inc()
        logger.error(f"❌ Escalate approval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/requests/expire")
async def expire_requests(db: Session = Depends(get_db)):
    """Expire all pending/partially_approved requests past expires_at."""
    now = datetime.now(timezone.utc)
    q = db.query(ApprovalRequest).filter(
        ApprovalRequest.request_status.in_(["pending", "partially_approved"]),
        ApprovalRequest.expires_at.isnot(None),
        ApprovalRequest.expires_at < now
    )
    count = q.count()
    q.update({ApprovalRequest.request_status: "expired", ApprovalRequest.completed_date: now}, synchronize_session=False)
    db.commit()
    return {"expired": count}


@router.post("/approver-limits", status_code=201)
async def create_or_update_approver_limit(
        req: ApproverLimitRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("budgets.manage"))
):
    """Create or update an approver's limit."""
    try:
        approver = db.query(User).filter(
            User.user_id == uuid.UUID(req.approver_user_id),
            User.tenant_id == uuid.UUID(ctx.tenant_id)
        ).first()
        if not approver:
            raise HTTPException(status_code=404, detail="Approver user not found or not in tenant")

        approver_limit = db.query(ApproverLimit).filter(
            ApproverLimit.approver_user_id == uuid.UUID(req.approver_user_id),
            ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id),
            ApproverLimit.org_unit_id == (uuid.UUID(req.org_unit_id) if req.org_unit_id else None)
        ).with_for_update().first()

        if approver_limit:
            approver_limit.limit_amount_minor = req.limit_amount_minor
            approver_limit.reset_period = req.reset_period
            approver_limit.reset_anchor = req.reset_anchor_date
            approver_limit.updated_at = datetime.now(timezone.utc)
        else:
            approver_limit = ApproverLimit(
                id=uuid.uuid4(),
                approver_user_id=uuid.UUID(req.approver_user_id),
                tenant_id=uuid.UUID(ctx.tenant_id),
                org_unit_id=uuid.UUID(req.org_unit_id) if req.org_unit_id else None,
                limit_amount_minor=req.limit_amount_minor,
                consumed_amount_minor=0,
                reset_period=req.reset_period,
                reset_anchor=req.reset_anchor_date,
                last_reset_at=datetime.now(timezone.utc)
            )
            db.add(approver_limit)

        db.commit()
        db.refresh(approver_limit)
        return {
            "id": str(approver_limit.id),
            "approver_user_id": str(approver_limit.approver_user_id),
            "org_unit_id": str(approver_limit.org_unit_id) if approver_limit.org_unit_id else None,
            "limit_amount_minor": approver_limit.limit_amount_minor,
            "consumed_amount_minor": approver_limit.consumed_amount_minor,
            "reset_period": approver_limit.reset_period,
            "reset_anchor_date": approver_limit.reset_anchor.isoformat() if approver_limit.reset_anchor else None,
            "last_reset_at": approver_limit.last_reset_at.isoformat() if approver_limit.last_reset_at else None,
            "updated_at": approver_limit.updated_at.isoformat() if approver_limit.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to set approver limit: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/approver-limits")
async def list_approver_limits(
        approver_user_id: Optional[str] = Query(None),
        org_unit_id: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("budgets.manage"))
):
    """List approver limits."""
    try:
        q = db.query(ApproverLimit).filter(ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id))
        if approver_user_id:
            q = q.filter(ApproverLimit.approver_user_id == uuid.UUID(approver_user_id))
        if org_unit_id:
            q = q.filter(ApproverLimit.org_unit_id == uuid.UUID(org_unit_id))
        limits = q.all()
        return [
            {
                "id": str(l.id),
                "approver_user_id": str(l.approver_user_id),
                "org_unit_id": str(l.org_unit_id) if l.org_unit_id else None,
                "limit_amount_minor": l.limit_amount_minor,
                "consumed_amount_minor": l.consumed_amount_minor,
                "reset_period": l.reset_period,
                "reset_anchor_date": l.reset_anchor.isoformat() if l.reset_anchor else None,
                "last_reset_at": l.last_reset_at.isoformat() if l.last_reset_at else None,
                "created_at": l.created_at.isoformat(),
                "updated_at": l.updated_at.isoformat() if l.updated_at else None
            }
            for l in limits
        ]
    except Exception as e:
        logger.error(f"❌ Failed to list approver limits: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/limits/reset")
async def reset_approver_limits(db: Session = Depends(get_db)):
    """Reset approver limits according to their reset_period."""
    now = datetime.now(timezone.utc)
    limits = db.query(ApproverLimit).with_for_update().all()
    reset_count = 0
    for lim in limits:
        reset = False
        if lim.reset_period == "daily":
            reset = (not lim.last_reset_at) or (lim.last_reset_at.date() < now.date())
        elif lim.reset_period == "weekly":
            reset = (not lim.last_reset_at) or (lim.last_reset_at.isocalendar()[1] != now.isocalendar()[1])
        elif lim.reset_period == "monthly":
            reset = (not lim.last_reset_at) or ((lim.last_reset_at.year, lim.last_reset_at.month) != (now.year, now.month))
        if reset:
            lim.consumed_amount_minor = 0
            lim.last_reset_at = now
            reset_count += 1
    db.commit()
    return {"reset": reset_count}


@router.post("/requests/{request_id}/cancel")
async def cancel_approval_request(
        request_id: str,
        cancellation_reason: Optional[str] = Query(None, description="Cancellation reason"),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.requests.create"))
):
    """Allow requesters to cancel pending requests"""
    try:
        # Get the approval request
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()

        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        # SECURITY: Only requester or admin can cancel
        if str(approval_request.requested_by) != ctx.user_id and "*" not in ctx.permissions:
            raise HTTPException(status_code=403, detail="Only the requester can cancel this request")

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, approval_request.tenant_id)

        # Only allow cancellation of pending requests
        if approval_request.request_status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel request with status: {approval_request.request_status}"
            )

        # Update request status
        approval_request.request_status = "canceled"
        approval_request.completed_date = datetime.now(timezone.utc)
        approval_request.updated_at = datetime.now(timezone.utc)

        # Update all pending approvers to canceled
        pending_approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.status == "pending"
        ).all()

        for approver in pending_approvers:
            approver.status = "canceled"
            approver.notes = cancellation_reason or "Request canceled by requester"
            approver.responded_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(f"✅ Approval request {request_id} canceled by {ctx.user_id}")

        return {
            "request_id": request_id,
            "request_number": approval_request.request_number,
            "status": approval_request.request_status,
            "canceled_at": approval_request.completed_date.isoformat(),
            "canceled_by": ctx.user_id,
            "cancellation_reason": cancellation_reason
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Cancel approval request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")