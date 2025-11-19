import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import Tenant, User, ApprovalChain, ApprovalChainStep, ApprovalRequest, ApprovalRequestApprover, \
    UserCostCentre, SpendingEvent, Role, UserRole, RoleScope
from Schemas import UserContext, ApprovalChainRequest, ApprovalChainStepRequest, ApprovalRequestRequest, \
    ApprovalResponseRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission, resolve_approvers_for_step, check_tenant_access
from utils.logger import logger
from utils.metrics import req_total, req_duration

app = APIRouter()

# ==================================================================================
# APPROVALS MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/approvals/chains", status_code=201)
async def create_approval_chain(
        req: ApprovalChainRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.chains.manage"))
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


@app.get("/v1/approvals/chains")
async def list_approval_chains(
        tenant_id: Optional[str] = Query(None),
        chain_type: Optional[str] = Query(None),
        is_active: Optional[bool] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(require_permission("approvals.chains.manage"))
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


@app.post("/v1/approvals/chains/steps", status_code=201)
async def create_approval_chain_step(
        req: ApprovalChainStepRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.chains.manage"))
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


@app.get("/v1/approvals/chains/{chain_id}/steps")
async def list_chain_steps(
        chain_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.chains.manage"))
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


@app.post("/v1/approvals/requests", status_code=201)
async def create_approval_request(
        req: ApprovalRequestRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.requests.create"))
):
    """Create a new approval request"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_request", status="start").inc()

        # CRITICAL: Tenant isolation
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify chain belongs to tenant
        chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_id == uuid.UUID(req.chain_id),
            ApprovalChain.tenant_id == uuid.UUID(req.tenant_id)
        ).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")

        # Generate request number
        request_number = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        # CRITICAL: Use authenticated user as requester
        approval_request = ApprovalRequest(
            request_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            chain_id=uuid.UUID(req.chain_id),
            request_number=request_number,
            request_type=req.request_type,
            request_data=req.request_data,
            requested_by=uuid.UUID(ctx.user_id),  # FIXED: Use authenticated user
            request_status="pending",
            current_step_number=1,
            total_amount_minor=req.total_amount_minor,
            currency=req.currency,
            due_date=req.due_date
        )
        db.add(approval_request)
        db.flush()  # Get the request_id

        # Get chain steps and create approver assignments
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(req.chain_id)
        ).order_by(ApprovalChainStep.step_number).all()

        if not steps:
            raise HTTPException(status_code=400, detail="Approval chain has no steps")

        for step in steps:
            approver_user_ids = resolve_approvers_for_step(
                db,
                step,
                req.tenant_id,
                req.request_data
            )
            
            # FIXED: No self-approval fallback - provide detailed error message
            if not approver_user_ids:
                # Check if role exists
                role = db.query(Role).filter(
                    Role.code == step.approver_role,
                    Role.tenant_id == uuid.UUID(req.tenant_id)
                ).first()
                
                if not role:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No approvers found for step {step.step_number}: Role '{step.approver_role}' does not exist for this tenant. Please create the role first."
                    )
                
                # Check if any users have this role
                user_count = db.query(UserRole).join(
                    User, UserRole.user_id == User.user_id
                ).filter(
                    UserRole.role_id == role.role_id,
                    User.tenant_id == uuid.UUID(req.tenant_id),
                    User.active == True
                ).count()
                
                if user_count == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No approvers found for step {step.step_number}: No users have the role '{step.approver_role}' for this tenant. Please assign users to this role."
                    )
                
                raise HTTPException(
                    status_code=400,
                    detail=f"No approvers found for step {step.step_number} with scope '{step.approver_scope}'. Check chain configuration and ensure users with role '{step.approver_role}' have appropriate scopes."
                )

            for approver_user_id in approver_user_ids:
                approver = ApprovalRequestApprover(
                    id=uuid.uuid4(),
                    request_id=approval_request.request_id,
                    approver_user_id=uuid.UUID(approver_user_id),
                    approver_role=step.approver_role,
                    step_number=step.step_number,
                    status="pending"
                )
                db.add(approver)

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
            "chain_id": str(approval_request.chain_id),
            "request_type": approval_request.request_type,
            "requested_by": str(approval_request.requested_by),
            "request_status": approval_request.request_status,
            "total_amount_minor": approval_request.total_amount_minor,
            "currency": approval_request.currency,
            "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
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


@app.get("/v1/approvals/requests")
async def list_approval_requests(
        tenant_id: Optional[str] = Query(None),
        request_type: Optional[str] = Query(None),
        request_status: Optional[str] = Query(None),
        requested_by: Optional[str] = Query(None),
        approver_user_id: Optional[str] = Query(None, description="Filter by approver user ID (for managers to see their pending requests)"),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(require_permission("approvals.requests.view"))
):
    """List approval requests (managers can filter by approver_user_id to see their pending requests)"""
    try:
        q = db.query(ApprovalRequest)
        
        # SECURITY: Filter by tenant
        if tenant_id:
            check_tenant_access(ctx, uuid.UUID(tenant_id))
            q = q.filter(ApprovalRequest.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(ApprovalRequest.tenant_id == ctx.tenant_id)
        
        if request_type:
            q = q.filter(ApprovalRequest.request_type == request_type)
        if request_status:
            q = q.filter(ApprovalRequest.request_status == request_status)
        if requested_by:
            q = q.filter(ApprovalRequest.requested_by == uuid.UUID(requested_by))
        
        # Filter by approver (for managers to see their pending requests)
        if approver_user_id:
            # SECURITY: Verify user can only see requests where they are an approver
            if approver_user_id != ctx.user_id and approver_user_id not in ctx.manager_of:
                raise HTTPException(status_code=403, detail="Cannot view requests for other approvers")
            
            # Join with ApprovalRequestApprover to filter by approver
            q = q.join(
                ApprovalRequestApprover,
                ApprovalRequestApprover.request_id == ApprovalRequest.request_id
            ).filter(
                ApprovalRequestApprover.approver_user_id == uuid.UUID(approver_user_id),
                ApprovalRequestApprover.status == "pending"
            )

        # Use distinct() if filtering by approver to avoid duplicates
        if approver_user_id:
            q = q.distinct()
        
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
                    "approved_amount_minor": r.approved_amount_minor,
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


@app.get("/v1/approvals/requests/{request_id}")
async def get_approval_request(
        request_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.requests.view"))
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


@app.get("/v1/approvals/requests/{request_id}/approvers")
async def get_request_approvers(
        request_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.requests.view"))
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


@app.post("/v1/approvals/requests/{request_id}/respond")
async def respond_to_approval_request(
        request_id: str,
        req: ApprovalResponseRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("approvals.requests.respond"))
):
    """Respond to an approval request (approve or deny)"""
    start = datetime.now()
    budget_allocated = False
    allocated_amount_minor = 0
    
    try:
        req_total.labels(operation="respond_approval", status="start").inc()

        # Get the approval request
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()

        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, approval_request.tenant_id)

        if approval_request.request_status != "pending":
            raise HTTPException(status_code=400,
                                detail=f"Request is not pending (status: {approval_request.request_status})")

        # FIXED: Always try to find approver using the provided approver_user_id first
        # Then verify authorization (user must be the approver themselves OR be authorized to respond for them)
        approver = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id),
            ApprovalRequestApprover.step_number == approval_request.current_step_number,
            ApprovalRequestApprover.status == "pending"
        ).first()
        
        # Verify authorization: user must be the approver themselves OR be authorized (manager relationship)
        if approver:
            # Check if authenticated user is the approver themselves
            if req.approver_user_id != ctx.user_id:
                # Check if user is authorized to respond for this approver (manager relationship)
                if req.approver_user_id not in ctx.manager_of:
                    raise HTTPException(
                        status_code=403,
                        detail=f"You are not authorized to respond for approver {req.approver_user_id}. You can only respond for your own approvals (use your own user_id) or for users you manage."
                    )
        
        if not approver:
            # Provide detailed error message
            # Check if the provided approver_user_id exists for any step
            approver_exists = db.query(ApprovalRequestApprover).filter(
                ApprovalRequestApprover.request_id == uuid.UUID(request_id),
                ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id)
            ).first()
            
            if approver_exists:
                if approver_exists.step_number != approval_request.current_step_number:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Approver {req.approver_user_id} is assigned to step {approver_exists.step_number}, but the request is currently at step {approval_request.current_step_number}. Please wait for the request to reach that step."
                    )
                elif approver_exists.status != "pending":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Approver {req.approver_user_id} has already responded to this request (status: {approver_exists.status})."
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Approver assignment not found for step {approval_request.current_step_number}."
                    )
            else:
                # Check if authenticated user is an approver (maybe they should use their own ID)
                user_is_approver = db.query(ApprovalRequestApprover).filter(
                    ApprovalRequestApprover.request_id == uuid.UUID(request_id),
                    ApprovalRequestApprover.approver_user_id == uuid.UUID(ctx.user_id),
                    ApprovalRequestApprover.status == "pending"
                ).first()
                
                if user_is_approver:
                    if user_is_approver.step_number != approval_request.current_step_number:
                        raise HTTPException(
                            status_code=400,
                            detail=f"You are an approver for step {user_is_approver.step_number}, but the request is currently at step {approval_request.current_step_number}. Use your own user_id ({ctx.user_id}) in approver_user_id and wait for your step."
                        )
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Approver assignment not found. Try using your own user_id ({ctx.user_id}) in approver_user_id field."
                        )
                else:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Approver {req.approver_user_id} is not assigned to this request. Only assigned approvers can respond. If you are an approver, use your own user_id in the approver_user_id field."
                    )

        # SECURITY: Verify approver still has required role and scope
        step = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == approval_request.chain_id,
            ApprovalChainStep.step_number == approval_request.current_step_number
        ).first()

        if step:
            # Verify role assignment still exists (use the approver we found)
            role = db.query(Role).filter(
                Role.code == step.approver_role,
                Role.tenant_id == approval_request.tenant_id
            ).first()
            if role:
                user_role = db.query(UserRole).filter(
                    UserRole.user_id == approver.approver_user_id,  # Use the approver we found
                    UserRole.role_id == role.role_id
                ).first()
                if not user_role:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Approver no longer has required role: {step.approver_role}"
                    )

            # Verify scope if not tenant-wide
            if step.approver_scope != "tenant":
                from core.permission_check_helpers import resolve_resource_id_for_scope
                target_resource_id = resolve_resource_id_for_scope(
                    approval_request.request_data or {},
                    str(approval_request.tenant_id),
                    step.approver_scope
                )

                if target_resource_id and role:
                    # Check if user has scope for this resource (use the approver we found)
                    user_scope = db.query(RoleScope).join(
                        UserRole, RoleScope.role_id == UserRole.role_id
                    ).filter(
                        UserRole.user_id == approver.approver_user_id,  # Use the approver we found
                        RoleScope.role_id == role.role_id,
                        RoleScope.resource_type == step.approver_scope
                    ).filter(
                        (RoleScope.resource_id == uuid.UUID(target_resource_id)) |
                        (RoleScope.resource_id.is_(None))
                    ).first()

                    if not user_scope:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Approver no longer has required scope: {step.approver_scope} for resource {target_resource_id}"
                        )

        # NEW: Handle amount modification
        if req.approved and req.modified_amount_minor is not None:
            if req.modified_amount_minor <= 0:
                raise HTTPException(status_code=400, detail="Modified amount must be positive")
            
            # Update request amount
            original_amount = approval_request.total_amount_minor
            approval_request.total_amount_minor = req.modified_amount_minor
            
            # Track modification history
            modification_history = approval_request.amount_modification_history or []
            modification_history.append({
                "step": approval_request.current_step_number,
                "approver_user_id": req.approver_user_id,
                "original_amount": original_amount,
                "modified_amount": req.modified_amount_minor,
                "reason": req.modification_reason,
                "modified_at": datetime.now(timezone.utc).isoformat()
            })
            approval_request.amount_modification_history = modification_history
            
            logger.info(f"💰 Amount modified from {original_amount} to {req.modified_amount_minor} by {req.approver_user_id}")

        # Update approver response (use the approver we found, which may be for ctx.user_id or req.approver_user_id)
        approver.status = "approved" if req.approved else "denied"
        approver.notes = req.notes
        approver.responded_at = datetime.now(timezone.utc)
        
        # Log who responded
        logger.info(f"✅ Approver {approver.approver_user_id} responded to request {request_id}: {'approved' if req.approved else 'denied'}")

        # Update request status
        if not req.approved:
            # Denial at any step fails the request
            approval_request.request_status = "denied"
            approval_request.completed_date = datetime.now(timezone.utc)
        else:
            # Check if there are more steps
            max_step = db.query(func.max(ApprovalChainStep.step_number)).filter(
                ApprovalChainStep.approval_chain_id == approval_request.chain_id
            ).scalar()

            if approval_request.current_step_number >= max_step:
                # Last step completed and approved
                approval_request.request_status = "approved"
                approval_request.completed_date = datetime.now(timezone.utc)
                # Set approved amount (use modified amount if available, otherwise original)
                approval_request.approved_amount_minor = approval_request.total_amount_minor
                
                # Handle budget allocation for budget_request type
                if approval_request.request_type == "budget_request":
                    request_data = approval_request.request_data or {}
                    user_id = request_data.get("user_id")
                    # Use approved_amount_minor if set, otherwise use total_amount_minor
                    amount_minor = approval_request.approved_amount_minor or approval_request.total_amount_minor or 0
                    
                    if user_id and amount_minor > 0:
                        # FIXED: Use row locking to prevent race conditions
                        user_cc = db.query(UserCostCentre).filter(
                            UserCostCentre.user_id == uuid.UUID(user_id)
                        ).with_for_update().first()
                        
                        if user_cc:
                            # Allocate budget to user
                            user_cc.allocated_budget_minor += amount_minor
                            
                            # Create spending event for audit
                            spending_event = SpendingEvent(
                                event_id=uuid.uuid4(),
                                event_type="budget_allocated",
                                user_id=uuid.UUID(user_id),
                                cost_centre_id=user_cc.cost_centre_id,
                                order_id=None,
                                approval_request_id=approval_request.request_id,
                                amount_minor=amount_minor,
                                currency_code=user_cc.currency_code,
                                event_metadata={
                                    "request_number": approval_request.request_number,
                                    "approved_by": str(approver.approver_user_id)  # Use the actual approver who responded
                                }
                            )
                            db.add(spending_event)
                            
                            budget_allocated = True
                            allocated_amount_minor = amount_minor
                            
                            logger.info(f"✅ Budget allocated: {amount_minor} to user {user_id} via approval {request_id}")
                        else:
                            raise HTTPException(
                                status_code=404,
                                detail=f"User {user_id} not found in cost centre assignments"
                            )
            else:
                # Move to next step
                approval_request.current_step_number += 1

        approval_request.updated_at = datetime.now(timezone.utc)
        
        # FIXED: Wrap budget allocation in same transaction - commit both approval and budget
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Budget allocation failed: {e}")
            raise HTTPException(status_code=500, detail="Budget allocation failed")

        req_total.labels(operation="respond_approval", status="success").inc()
        req_duration.labels(operation="respond_approval").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(
            f"✅ Approval request {request_id} {'approved' if req.approved else 'denied'} by {req.approver_user_id}")

        return {
            "request_id": request_id,
            "request_number": approval_request.request_number,
            "approver_user_id": str(approver.approver_user_id),  # Use the actual approver who responded
            "status": approver.status,
            "notes": approver.notes,
            "responded_at": approver.responded_at.isoformat(),
            "request_status": approval_request.request_status,
            "current_step_number": approval_request.current_step_number,
            "total_amount_minor": approval_request.total_amount_minor,
            "approved_amount_minor": approval_request.approved_amount_minor,
            "budget_allocated": budget_allocated,
            "allocated_amount_minor": allocated_amount_minor if budget_allocated else None,
            "completed": approval_request.request_status in ["approved", "denied"]
        }
    except ValueError:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="respond_approval", status="error").inc()
        logger.error(f"❌ Respond to approval failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests/{request_id}/cancel")
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


@app.post("/v1/approvals/requests/{request_id}/close", status_code=200)
async def close_approval_request(
    request_id: str,
    closure_reason: Optional[str] = Query(None, description="Reason for closure"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("approvals.requests.view"))
):
    """Close an approved/denied approval request"""
    try:
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, approval_request.tenant_id)
        
        # Only allow closure of completed requests
        if approval_request.request_status not in ["approved", "denied"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot close request with status: {approval_request.request_status}"
            )
        
        # Check if already closed
        if approval_request.request_status == "closed":
            raise HTTPException(status_code=400, detail="Request is already closed")
        
        # Update status
        approval_request.request_status = "closed"
        approval_request.completed_date = datetime.now(timezone.utc)
        approval_request.updated_at = datetime.now(timezone.utc)
        
        # Store closure reason in request_data if needed
        request_data = approval_request.request_data or {}
        request_data["closure_reason"] = closure_reason
        request_data["closed_by"] = ctx.user_id
        request_data["closed_at"] = datetime.now(timezone.utc).isoformat()
        approval_request.request_data = request_data
        
        db.commit()
        
        logger.info(f"✅ Approval request {request_id} closed by {ctx.user_id}")
        
        return {
            "request_id": request_id,
            "request_number": approval_request.request_number,
            "status": approval_request.request_status,
            "closed_at": approval_request.completed_date.isoformat(),
            "closed_by": ctx.user_id,
            "closure_reason": closure_reason
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Close approval request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")