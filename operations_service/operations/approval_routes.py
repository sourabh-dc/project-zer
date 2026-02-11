"""
Approval Service - Simplified with Policy Engine Integration

Changes from original:
- Removed partial approval (full approve or deny only)
- Removed escalation functionality
- Integrated Policy Engine for approval rules:
  - approval.respond: Check if approver can respond (expiry, org unit, limit)
  - approval.cancel: Check if user can cancel (requester or admin only)
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
import httpx
import os

from operations_service.Models import Tenant, User, ApprovalRequest, ApprovalRequestApprover, \
    UserCostCentre, SpendingEvent, ApproverLimit, CostCentre, ApprovalLog, UserRole, Role, OrgUnit, \
    ApprovalChain, ApprovalChainStep, BudgetRequest, BudgetApproval
from operations_service.Schemas import UserContext, ApprovalChainRequest, ApprovalChainStepRequest, \
    ApprovalRequestRequest, \
    ApprovalResponseRequest, ApproverLimitRequest, BudgetRequestOut, BudgetRequestCreate, BudgetApprovalCreate
from operations_service.core.db_config import get_db
from operations_service.core.user_auth import check_user_authorization
from operations_service.utils.logger import logger
from operations_service.utils.metrics import req_total, req_duration


router = APIRouter(prefix="/approvals", tags=["Approvals"])

POLICY_ENGINE_URL = os.getenv("POLICY_ENGINE_URL", "http://localhost:8004")


async def evaluate_policy(action: str, subject: dict, resource: dict, context: dict = None) -> dict:
    """Evaluate a policy against the Policy Engine."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{POLICY_ENGINE_URL}/v1/policy-engine/evaluate",
                json={
                    "action": action,
                    "subject": subject,
                    "resource": resource,
                    "context": context or {}
                }
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Policy Engine error: {response.status_code} - {response.text}")
                return {"allowed": True, "effect": "allow", "reason": "Policy Engine unavailable"}
    except Exception as e:
        logger.error(f"Policy Engine connection error: {e}")
        return {"allowed": True, "effect": "allow", "reason": f"Policy Engine unavailable: {e}"}


# ==================================================================================
# APPROVAL CHAINS ENDPOINTS
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

        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

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

        chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_id == uuid.UUID(req.approval_chain_id)
        ).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")

        step = ApprovalChainStep(
            id=uuid.uuid4(),
            approval_chain_id=uuid.UUID(req.approval_chain_id),
            step_number=req.step_number,
            approver_role=req.approver_role,
            approver_scope=req.approver_scope,
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


@router.post("/chains/{chain_id}/steps", status_code=201)
async def create_chain_step_alias(
        chain_id: str,
        req: ApprovalChainStepRequest,
        db: Session = Depends(get_db)
):
    req.approval_chain_id = chain_id
    return await create_approval_chain_step(req, db)


# ==================================================================================
# APPROVAL REQUESTS ENDPOINTS
# ==================================================================================

@router.post("/requests", status_code=201)
async def create_approval_request(
        req: ApprovalRequestRequest,
        current_user_id: str,
        db: Session = Depends(get_db),
):
    """
    Create a new approval request.
    Assigns all eligible approvers within the org unit who have sufficient approval limits.
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
                raise HTTPException(status_code=404, detail="Organizational unit not found")

        request_number = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        approval_request_id = uuid.uuid4()
        approval_request = ApprovalRequest(
            request_id=approval_request_id,
            tenant_id=uuid.UUID(req.tenant_id),
            org_unit_id=uuid.UUID(req.org_unit_id) if req.org_unit_id else None,
            chain_id=None,
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

        # Find eligible approvers with sufficient limits
        approver_user_ids = []

        # Get all tenant_admin users in the org unit (or tenant-wide if no org unit)
        admin_roles = db.query(UserRole).join(Role, Role.role_id == UserRole.role_id).filter(
            UserRole.tenant_id == uuid.UUID(req.tenant_id),
            Role.code == "tenant_admin"
        ).all()

        for ur in admin_roles:
            # Check if approver has sufficient limit
            approver_limit = db.query(ApproverLimit).filter(
                ApproverLimit.approver_user_id == ur.user_id,
                ApproverLimit.tenant_id == uuid.UUID(req.tenant_id)
            ).first()

            if approver_limit:
                # Check org unit match if specified
                if req.org_unit_id and approver_limit.org_unit_id:
                    if str(approver_limit.org_unit_id) != req.org_unit_id:
                        continue

                # Check remaining limit
                remaining_limit = (approver_limit.limit_amount_minor or 0) - (approver_limit.consumed_amount_minor or 0)
                if remaining_limit >= req.total_amount_minor:
                    approver_user_ids.append(ur.user_id)
            else:
                # No limit defined - allow (unlimited)
                approver_user_ids.append(ur.user_id)

        if not approver_user_ids:
            raise HTTPException(status_code=500, detail="No eligible approvers found with sufficient limits")

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
            "currency": approval_request.currency,
            "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
            "expires_at": approval_request.expires_at.isoformat() if approval_request.expires_at else None,
            "created_at": approval_request.created_at.isoformat(),
            "approvers_assigned": len(approver_user_ids)
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
                    "request_type": r.request_type,
                    "requested_by": str(r.requested_by),
                    "request_status": r.request_status,
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

        approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()

        return {
            "request_id": str(request.request_id),
            "request_number": request.request_number,
            "tenant_id": str(request.tenant_id),
            "request_type": request.request_type,
            "request_data": request.request_data,
            "requested_by": str(request.requested_by),
            "request_status": request.request_status,
            "total_amount_minor": request.total_amount_minor,
            "currency": request.currency,
            "due_date": request.due_date.isoformat() if request.due_date else None,
            "expires_at": request.expires_at.isoformat() if request.expires_at else None,
            "completed_date": request.completed_date.isoformat() if request.completed_date else None,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_role": a.approver_role,
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
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()

        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        approvers = db.query(ApprovalRequestApprover, User).join(
            User, ApprovalRequestApprover.approver_user_id == User.user_id
        ).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).all()

        return {
            "request_id": request_id,
            "request_number": request.request_number,
            "request_status": request.request_status,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_email": u.email,
                    "approver_name": u.display_name,
                    "approver_role": a.approver_role,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None,
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
    Respond to an approval request with APPROVE or REJECT only.
    No partial approvals - full amount or reject.

    Policy Engine validates:
    - Request not expired
    - Approver in same org unit as requester
    - Approver has sufficient limit
    """
    start = datetime.now()
    try:
        req_total.labels(operation="respond_approval", status="start").inc()

        # Lock the request row
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).with_for_update().first()

        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        if approval_request.request_status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Request not actionable (status: {approval_request.request_status})"
            )

        # Get approver assignment
        approver = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id),
            ApprovalRequestApprover.status == "pending"
        ).with_for_update().first()

        if not approver:
            raise HTTPException(status_code=404, detail="Approver assignment not found or already responded")

        # Get approver's limit info
        approver_limit = db.query(ApproverLimit).filter(
            ApproverLimit.approver_user_id == uuid.UUID(req.approver_user_id),
            ApproverLimit.tenant_id == approval_request.tenant_id
        ).first()

        remaining_limit = None
        if approver_limit:
            remaining_limit = (approver_limit.limit_amount_minor or 0) - (approver_limit.consumed_amount_minor or 0)

        # Get approver's org unit
        approver_user = db.query(User).filter(User.user_id == uuid.UUID(req.approver_user_id)).first()

        # Evaluate policy via Policy Engine
        policy_result = await evaluate_policy(
            action="approval.respond",
            subject={
                "user_id": req.approver_user_id,
                "tenant_id": str(approval_request.tenant_id),
                "org_unit_id": str(approver_user.home_org_unit_id) if approver_user and approver_user.home_org_unit_id else None,
                "roles": [approver.approver_role],
                "approver_limit_remaining": remaining_limit
            },
            resource={
                "request_id": request_id,
                "request_amount": approval_request.total_amount_minor,
                "org_unit_id": str(approval_request.org_unit_id) if approval_request.org_unit_id else None,
                "is_expired": approval_request.expires_at and datetime.now(timezone.utc) > approval_request.expires_at,
                "expires_at": approval_request.expires_at.isoformat() if approval_request.expires_at else None
            }
        )

        if not policy_result.get("allowed", True):
            reason = policy_result.get("reason", "Policy evaluation failed")

            # If expired, update status
            if "expired" in reason.lower():
                approval_request.request_status = "expired"
                db.commit()

            raise HTTPException(status_code=403, detail=reason)

        # Validate response - only "approved" or "rejected" allowed
        response = req.response.lower()
        if response not in ["approved", "rejected"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid response. Only 'approved' or 'rejected' allowed."
            )

        now_ts = datetime.now(timezone.utc)
        budget_allocated = False
        allocated_amount_minor = 0

        if response == "approved":
            approve_amount = approval_request.total_amount_minor

            # Update approver limit
            if approver_limit:
                approver_limit.consumed_amount_minor = (approver_limit.consumed_amount_minor or 0) + approve_amount

            # Credit budget if budget request
            if approval_request.request_type.startswith("budget"):
                request_data = approval_request.request_data or {}
                user_id = request_data.get("user_id")

                if user_id:
                    user_cc = db.query(UserCostCentre).filter(
                        UserCostCentre.user_id == uuid.UUID(user_id)
                    ).with_for_update().first()

                    if user_cc:
                        cc = db.query(CostCentre).filter(
                            CostCentre.cost_centre_id == user_cc.cost_centre_id
                        ).with_for_update().first()

                        if cc:
                            total_alloc = db.query(func.coalesce(func.sum(UserCostCentre.allocated_budget_minor), 0)).filter(
                                UserCostCentre.cost_centre_id == user_cc.cost_centre_id
                            ).scalar() or 0

                            if total_alloc + approve_amount > cc.budget_minor:
                                raise HTTPException(status_code=400, detail="Cost centre budget exceeded")

                            user_cc.allocated_budget_minor += approve_amount

                            spending_event = SpendingEvent(
                                event_id=uuid.uuid4(),
                                event_type="budget_allocated",
                                user_id=user_cc.user_id,
                                cost_centre_id=user_cc.cost_centre_id,
                                order_id=None,
                                approval_request_id=approval_request.request_id,
                                amount_minor=approve_amount,
                                currency_code=user_cc.currency_code,
                                event_metadata={
                                    "request_number": approval_request.request_number,
                                    "approved_by": req.approver_user_id
                                }
                            )
                            db.add(spending_event)
                            budget_allocated = True
                            allocated_amount_minor = approve_amount

            approver.status = "approved"
            approver.approved_amount_minor = approve_amount
            approval_request.request_status = "approved"
            approval_request.remaining_amount_minor = 0
            approval_request.completed_date = now_ts

        else:  # rejected
            approver.status = "rejected"
            approver.approved_amount_minor = 0
            approval_request.request_status = "rejected"
            approval_request.completed_date = now_ts

        approver.responded_at = now_ts
        approver.notes = req.notes

        # Log the action
        log_entry = ApprovalLog(
            id=uuid.uuid4(),
            request_id=approval_request.request_id,
            actor_id=uuid.UUID(req.approver_user_id),
            action=response,
            amount_minor=approver.approved_amount_minor,
            remaining_amount_minor=approval_request.remaining_amount_minor,
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


@router.post("/requests/expire")
async def expire_requests(db: Session = Depends(get_db)):
    """Expire all pending requests past expires_at."""
    now = datetime.now(timezone.utc)
    q = db.query(ApprovalRequest).filter(
        ApprovalRequest.request_status == "pending",
        ApprovalRequest.expires_at.isnot(None),
        ApprovalRequest.expires_at < now
    )
    count = q.count()
    q.update({ApprovalRequest.request_status: "expired", ApprovalRequest.completed_date: now}, synchronize_session=False)
    db.commit()
    return {"expired": count}


@router.post("/requests/{request_id}/cancel")
async def cancel_approval_request(
        request_id: str,
        cancellation_reason: Optional[str] = Query(None, description="Cancellation reason"),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization("approvals.requests.create"))
):
    """
    Cancel a pending approval request.

    Policy Engine validates:
    - Only the requester or tenant admin can cancel
    """
    try:
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()

        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        # Evaluate cancellation policy
        policy_result = await evaluate_policy(
            action="approval.cancel",
            subject={
                "user_id": ctx.user_id,
                "tenant_id": ctx.tenant_id,
                "roles": ctx.roles if hasattr(ctx, 'roles') else []
            },
            resource={
                "request_id": request_id,
                "requested_by": str(approval_request.requested_by),
                "tenant_id": str(approval_request.tenant_id)
            }
        )

        if not policy_result.get("allowed", True):
            raise HTTPException(status_code=403, detail=policy_result.get("reason", "Not authorized to cancel"))

        if approval_request.request_status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel request with status: {approval_request.request_status}"
            )

        approval_request.request_status = "canceled"
        approval_request.completed_date = datetime.now(timezone.utc)
        approval_request.updated_at = datetime.now(timezone.utc)

        pending_approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.status == "pending"
        ).all()

        for approver in pending_approvers:
            approver.status = "canceled"
            approver.notes = cancellation_reason or "Request canceled"
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


# ==================================================================================
# APPROVER LIMITS ENDPOINTS
# ==================================================================================

@router.post("/approver-limits", status_code=201)
async def create_or_update_approver_limit(
        req: ApproverLimitRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization("budgets.manage"))
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
        ctx: UserContext = Depends(check_user_authorization("budgets.manage"))
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
        ctx: UserContext = Depends(check_user_authorization("approvals.requests.create"))
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

# Endpoint: Create a new budget request
@router.post("/requests/", response_model=BudgetRequestOut)
def create_request(request: BudgetRequestCreate, db: Session = Depends(get_db)):
    db_request = BudgetRequest(**request.dict())
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    return db_request


# Endpoint: Approve a request (partial or full)
@router.post("/requests/approve/")
def approve_request(approval: BudgetApprovalCreate, db: Session = Depends(get_db)):
    db_request = db.query(BudgetRequest).filter(BudgetRequest.id == approval.budget_request_id).first()
    if not db_request:
        raise HTTPException(status_code=404, detail="Budget request not found")

    db_approval = BudgetApproval(**approval.dict(), decision="approved")
    db.add(db_approval)
    db.commit()

    # Check total approved amount
    total_approved = sum([float(a.approved_amount) for a in db_request.approvals if a.decision == "approved"])
    if total_approved == float(db_request.amount):
        db_request.status = "fully_approved"
    elif total_approved > 0:
        db_request.status = "partially_approved"
    db.commit()
    db.refresh(db_request)

    return {"message": "Approval recorded", "status": db_request.status}


# Endpoint: List all requests
@router.get("/requests/", response_model=List[BudgetRequestOut])
def list_requests(db: Session = Depends(get_db)):
    return db.query(BudgetRequest).filter(
        BudgetRequest.status.in_(["pending", "partially_approved"])
    ).order_by(BudgetRequest.created_at.desc()).all()