# services/instant_budget.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from datetime import datetime, timezone, timedelta
import uuid
from typing import Optional

from core.db_config import get_db
from core.permission_check_helpers import require_permission, UserContext, check_tenant_access
from Models import UserCostCentre, SpendingEvent, User, ApproverLimit, InstantBudgetRequest, CostCentre, Tenant
from Schemas import InstantBudgetRequestCreate, InstantBudgetApproveRequest, InstantBudgetResponse, ApproverLimitRequest

router = APIRouter(prefix="/v1/instant-budget")

# Helper functions
async def auto_approve(db: Session, request: InstantBudgetRequest, reason: str):
    """Auto-approve small amount requests"""
    user_cc = db.query(UserCostCentre).filter(
        UserCostCentre.user_id == request.user_id,
        UserCostCentre.cost_centre_id == request.cost_centre_id
    ).with_for_update().first()
    
    if user_cc:
        user_cc.allocated_budget_minor += request.requested_amount_minor
        request.approved_amount_minor = request.requested_amount_minor
        request.remaining_amount_minor = 0
        request.status = "approved"
        request.approved_by = request.requested_by  # Auto-approved by system
        request.approved_at = datetime.now(timezone.utc)
        
        # Create spending event for audit
        spending_event = SpendingEvent(
            event_id=uuid.uuid4(),
            event_type="budget_allocated",
            user_id=request.user_id,
            cost_centre_id=request.cost_centre_id,
            order_id=None,
            approval_request_id=None,
            amount_minor=request.requested_amount_minor,
            currency_code=user_cc.currency_code,
            event_metadata={
                "request_id": str(request.request_id),
                "reason": reason,
                "auto_approved": True
            }
        )
        db.add(spending_event)
        db.commit()

def notify_managers(eligible_managers, request, requester_name):
    """Notify managers about pending request (stub - implement with your notification system)"""
    # TODO: Implement notification logic (push notifications, email, etc.)
    from utils.logger import logger
    logger.info(f"📧 Notifying {len(eligible_managers)} managers about request {request.request_id} from {requester_name}")

def escalate_after_90sec(request_id: str):
    """Escalate request after 90 seconds (stub - implement with your notification system)"""
    # TODO: Implement escalation logic
    from utils.logger import logger
    logger.info(f"⚠️ Escalating request {request_id} after 90 seconds")

def notify_shopper(user_id: str, message: str):
    """Notify shopper about approval (stub - implement with your notification system)"""
    # TODO: Implement notification logic
    from utils.logger import logger
    logger.info(f"✅ Notifying user {user_id}: {message}")

def notify_others(request_id: str, approver_name: str):
    """Notify other managers that request was approved (stub - implement with your notification system)"""
    # TODO: Implement notification logic
    from utils.logger import logger
    logger.info(f"📢 Notifying others that request {request_id} was approved by {approver_name}")

# 1. Owner allocates budget
@router.post("/allocate")
async def allocate_budget(
    user_id: str = Query(..., description="User ID to allocate budget to"),
    cost_centre_id: str = Query(..., description="Cost centre ID"),
    amount_minor: int = Query(..., ge=0, description="Amount in minor units"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("budgets.manage"))
):
    """Allocate budget to a user (Owner/Admin can allocate budget)"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, user.tenant_id)
        
        # Verify cost centre exists
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        
        # SECURITY: Verify cost centre belongs to same tenant
        check_tenant_access(ctx, cc.tenant_id)
        
        uc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id)
        ).with_for_update().first()
        
        if not uc:
            uc = UserCostCentre(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                cost_centre_id=uuid.UUID(cost_centre_id),
                allocated_budget_minor=amount_minor,
                spent_minor=0,
                currency_code=cc.currency_code
            )
            db.add(uc)
        else:
            uc.allocated_budget_minor += amount_minor
        
        db.commit()
        db.refresh(uc)
        
        from utils.logger import logger
        logger.info(f"✅ Allocated {amount_minor} to user {user_id} in cost centre {cost_centre_id}")
        
        return {
            "status": "allocated",
            "user_id": user_id,
            "cost_centre_id": cost_centre_id,
            "allocated_amount_minor": uc.allocated_budget_minor,
            "available_minor": uc.allocated_budget_minor - uc.spent_minor
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        from utils.logger import logger
        logger.error(f"❌ Budget allocation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Create/update approver limits (MUST come before /approve/{request_id} to avoid route conflict)
@router.post("/approver-limits")
async def create_approver_limit(
    req: ApproverLimitRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("budgets.manage"))
):
    """Create or update approver limit for a manager"""
    try:
        # Verify user exists
        approver_user = db.query(User).filter(User.user_id == uuid.UUID(req.user_id)).first()
        if not approver_user:
            raise HTTPException(status_code=404, detail="Approver user not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, approver_user.tenant_id)
        
        # Verify cost centre if provided
        if req.cost_centre_id:
            cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id)).first()
            if not cc:
                raise HTTPException(status_code=404, detail="Cost centre not found")
            check_tenant_access(ctx, cc.tenant_id)
        
        # Check if limit already exists
        existing = db.query(ApproverLimit).filter(
            ApproverLimit.user_id == uuid.UUID(req.user_id),
            ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id),
            ApproverLimit.cost_centre_id == (uuid.UUID(req.cost_centre_id) if req.cost_centre_id else None)
        ).first()
        
        if existing:
            # Update existing limit
            existing.daily_limit_minor = req.daily_limit_minor
            existing.monthly_limit_minor = req.monthly_limit_minor
            existing.currency_code = req.currency_code
            limit = existing
        else:
            # Create new limit
            limit = ApproverLimit(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(ctx.tenant_id),
                user_id=uuid.UUID(req.user_id),
                cost_centre_id=uuid.UUID(req.cost_centre_id) if req.cost_centre_id else None,
                daily_limit_minor=req.daily_limit_minor,
                monthly_limit_minor=req.monthly_limit_minor,
                currency_code=req.currency_code
            )
            db.add(limit)
        
        db.commit()
        db.refresh(limit)
        
        from utils.logger import logger
        logger.info(f"✅ Created/updated approver limit for user {req.user_id}")
        
        return {
            "id": str(limit.id),
            "user_id": str(limit.user_id),
            "cost_centre_id": str(limit.cost_centre_id) if limit.cost_centre_id else None,
            "daily_limit_minor": limit.daily_limit_minor,
            "monthly_limit_minor": limit.monthly_limit_minor,
            "daily_remaining_minor": limit.daily_limit_minor - limit.daily_spent_minor,
            "monthly_remaining_minor": limit.monthly_limit_minor - limit.monthly_spent_minor,
            "currency_code": limit.currency_code
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        from utils.logger import logger
        logger.error(f"❌ Create approver limit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# 2. Shopper requests top-up
@router.post("/request", status_code=201, response_model=InstantBudgetResponse)
async def create_request(
    req: InstantBudgetRequestCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("budgets.instant.request"))
):
    """Request instant budget top-up (Shopper/Employee can request urgent budget)"""
    try:
        # Verify cost centre exists
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, cc.tenant_id)
        
        # Verify user has access to this cost centre
        user_cc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(ctx.user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id)
        ).first()
        
        if not user_cc:
            raise HTTPException(
                status_code=403,
                detail="User not assigned to this cost centre"
            )
        
        amount = req.amount_minor
        cc_id = uuid.UUID(req.cost_centre_id)
        
        # Create request
        request = InstantBudgetRequest(
            request_id=uuid.uuid4(),
            tenant_id=uuid.UUID(ctx.tenant_id),
            user_id=uuid.UUID(ctx.user_id),
            cost_centre_id=cc_id,
            store_id=uuid.UUID(req.store_id) if req.store_id else None,
            requested_amount_minor=amount,
            remaining_amount_minor=amount,
            reason=req.reason or "Customer waiting",
            requested_by=uuid.UUID(ctx.user_id),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=3)
        )
        db.add(request)
        db.flush()  # Get request_id
        
        # Find eligible managers who can approve
        # First try cost centre specific limits
        eligible = db.query(ApproverLimit, User).join(
            User, ApproverLimit.user_id == User.user_id
        ).filter(
            User.active == True,
            User.tenant_id == uuid.UUID(ctx.tenant_id),
            ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id),
            ApproverLimit.cost_centre_id == cc_id,
            ApproverLimit.daily_limit_minor - ApproverLimit.daily_spent_minor >= amount
        ).all()
        
        # If none found, try global limits
        if not eligible:
            eligible = db.query(ApproverLimit, User).join(
                User, ApproverLimit.user_id == User.user_id
            ).filter(
                User.active == True,
                User.tenant_id == uuid.UUID(ctx.tenant_id),
                ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id),
                ApproverLimit.cost_centre_id.is_(None),  # Global limit
                ApproverLimit.daily_limit_minor - ApproverLimit.daily_spent_minor >= amount
            ).all()
        
        # Auto-approve small amounts if no eligible managers
        if not eligible and amount <= 500000:  # ₹5,000 auto-approve
            await auto_approve(db, request, "small_amount")
            db.refresh(request)
            return InstantBudgetResponse(
                request_id=str(request.request_id),
                status="approved",
                expires_at=request.expires_at.isoformat(),
                approved_amount_minor=request.approved_amount_minor,
                remaining_amount_minor=request.remaining_amount_minor,
                message="Auto-approved (small amount)"
            )
        
        if not eligible:
            request.status = "rejected"
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="No manager has sufficient limit to approve this request"
            )
        
        db.commit()
        
        # Schedule background tasks (get user info for notification)
        user = db.query(User).filter(User.user_id == uuid.UUID(ctx.user_id)).first()
        requester_name = user.display_name if user else ctx.user_id
        
        bg.add_task(notify_managers, eligible, request, requester_name)
        bg.add_task(escalate_after_90sec, str(request.request_id))
        
        from utils.logger import logger
        logger.info(f"✅ Created instant budget request {request.request_id} for user {ctx.user_id}")
        
        return InstantBudgetResponse(
            request_id=str(request.request_id),
            status="pending",
            expires_at=request.expires_at.isoformat(),
            approved_amount_minor=0,
            remaining_amount_minor=request.remaining_amount_minor,
            message=f"Request sent to {len(eligible)} eligible managers"
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        from utils.logger import logger
        logger.error(f"❌ Instant budget request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# 3. Manager approves (supports partial + auto-split)
@router.post("/approve/{request_id}")
async def approve(
    request_id: str,
    payload: InstantBudgetApproveRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("budgets.instant.approve"))
):
    """Approve instant budget request (Manager approves - first one wins)"""
    try:
        req = db.query(InstantBudgetRequest).filter(
            InstantBudgetRequest.request_id == uuid.UUID(request_id),
            InstantBudgetRequest.status == "pending"
        ).with_for_update().first()
        
        if not req:
            raise HTTPException(status_code=404, detail="Request not found or already processed")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, req.tenant_id)
        
        if req.expires_at < datetime.now(timezone.utc):
            req.status = "expired"
            db.commit()
            raise HTTPException(status_code=410, detail="Request has expired")
        
        # Find approver's limit
        limit = db.query(ApproverLimit).filter(
            ApproverLimit.user_id == uuid.UUID(ctx.user_id),
            ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id),
            or_(
                ApproverLimit.cost_centre_id == req.cost_centre_id,
                ApproverLimit.cost_centre_id.is_(None)  # Global limit
            )
        ).with_for_update().first()
        
        if not limit:
            raise HTTPException(status_code=403, detail="No approval limit found for this user")
        
        # Check available limit
        available = limit.daily_limit_minor - limit.daily_spent_minor
        approve_amt = min(
            payload.partial_amount_minor or req.remaining_amount_minor,
            available,
            req.remaining_amount_minor
        )
        
        if approve_amt <= 0:
            raise HTTPException(status_code=400, detail="Insufficient approval limit")
        
        if not payload.approve:
            req.status = "rejected"
            req.approved_by = uuid.UUID(ctx.user_id)
            req.approved_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "rejected", "message": "Request denied"}
        
        # Update request
        req.approved_amount_minor += approve_amt
        req.remaining_amount_minor -= approve_amt
        
        # Update approver limit
        limit.daily_spent_minor += approve_amt
        limit.monthly_spent_minor += approve_amt
        
        # Update user budget
        uc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == req.user_id,
            UserCostCentre.cost_centre_id == req.cost_centre_id
        ).with_for_update().first()
        
        if not uc:
            raise HTTPException(status_code=404, detail="User cost centre assignment not found")
        
        uc.allocated_budget_minor += approve_amt
        
        # Create spending event for audit
        spending_event = SpendingEvent(
            event_id=uuid.uuid4(),
            event_type="budget_allocated",
            user_id=req.user_id,
            cost_centre_id=req.cost_centre_id,
            order_id=None,
            approval_request_id=None,
            amount_minor=approve_amt,
            currency_code=uc.currency_code,
            event_metadata={
                "request_id": str(request_id),
                "approved_by": ctx.user_id,
                "instant_budget": True
            }
        )
        db.add(spending_event)
        
        # Mark as approved if fully approved
        if req.remaining_amount_minor <= 0:
            req.status = "approved"
            req.approved_by = uuid.UUID(ctx.user_id)  # ctx.user_id is already a string
            req.approved_at = datetime.now(timezone.utc)
        else:
            req.status = "partial"
        
        db.commit()
        
        from utils.logger import logger
        logger.info(f"✅ Approved {approve_amt} for request {request_id} by {ctx.user_id}")
        
        if req.status == "approved":
            approver_user = db.query(User).filter(User.user_id == uuid.UUID(ctx.user_id)).first()
            approver_name = approver_user.display_name if approver_user else ctx.user_id
            
            notify_shopper(str(req.user_id), f"₹{req.approved_amount_minor//100:,} approved!")
            notify_others(request_id, approver_name)
        
        return {
            "status": req.status,
            "approved_this_time": approve_amt,
            "remaining": req.remaining_amount_minor,
            "total_approved": req.approved_amount_minor,
            "request_id": request_id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        from utils.logger import logger
        logger.error(f"❌ Approval failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Dashboard
@router.get("/pending")
async def pending(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("budgets.instant.approve"))
):
    """Get pending instant budget requests (for managers)"""
    try:
        pending_requests = db.query(InstantBudgetRequest).filter(
            InstantBudgetRequest.status == "pending",
            InstantBudgetRequest.expires_at > datetime.now(timezone.utc),
            InstantBudgetRequest.tenant_id == uuid.UUID(ctx.tenant_id)  # SECURITY: Tenant isolation
        ).order_by(InstantBudgetRequest.created_at.desc()).all()
        
        return [
            {
                "request_id": str(r.request_id),
                "user_id": str(r.user_id),
                "cost_centre_id": str(r.cost_centre_id),
                "amount_minor": r.requested_amount_minor,
                "remaining_minor": r.remaining_amount_minor,
                "reason": r.reason,
                "expires_at": r.expires_at.isoformat(),
                "created_at": r.created_at.isoformat()
            }
            for r in pending_requests
        ]
    except Exception as e:
        from utils.logger import logger
        logger.error(f"❌ Get pending requests failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/my-limit")
async def my_limit(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("budgets.instant.approve"))
):
    """Get current approval limit for authenticated manager"""
    try:
        limit = db.query(ApproverLimit).filter(
            ApproverLimit.user_id == uuid.UUID(ctx.user_id),
            ApproverLimit.tenant_id == uuid.UUID(ctx.tenant_id)  # SECURITY: Tenant isolation
        ).first()
        
        if not limit:
            return {
                "has_limit": False,
                "daily_remaining_minor": 0,
                "monthly_remaining_minor": 0,
                "message": "No approval limit configured"
            }
        
        daily_remaining = limit.daily_limit_minor - limit.daily_spent_minor
        monthly_remaining = limit.monthly_limit_minor - limit.monthly_spent_minor
        
        return {
            "has_limit": True,
            "limit_id": str(limit.id),
            "cost_centre_id": str(limit.cost_centre_id) if limit.cost_centre_id else None,
            "daily_limit_minor": limit.daily_limit_minor,
            "daily_spent_minor": limit.daily_spent_minor,
            "daily_remaining_minor": daily_remaining,
            "monthly_limit_minor": limit.monthly_limit_minor,
            "monthly_spent_minor": limit.monthly_spent_minor,
            "monthly_remaining_minor": monthly_remaining,
            "currency_code": limit.currency_code
        }
    except Exception as e:
        from utils.logger import logger
        logger.error(f"❌ Get limit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
