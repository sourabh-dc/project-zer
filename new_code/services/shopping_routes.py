"""
Shopping & Spending Endpoints
Handles shopping transactions, budget deductions, and overspend scenarios
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from Models import User, UserCostCentre, SpendingEvent
from Schemas import ShoppingRequest, ShoppingResponse, UserContext
from core.db_config import get_db
from core.user_auth import get_user_context
from utils.logger import logger

router = APIRouter(prefix="/v1/shopping", tags=["Shopping"])


def notify_manager_overspend(user_id: str, manager_id: str, overspend_amount: int):
    """Notify manager about employee overspend"""
    logger.info(f"📧 NOTIFICATION: User {user_id} overspent by £{overspend_amount / 100:.2f}. Notifying manager {manager_id}")
    # TODO: Implement actual notification (email, push, etc.)


@router.post("/purchase", status_code=201, response_model=ShoppingResponse)
async def record_purchase(
    req: ShoppingRequest,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_user_context)
):
    """
    Record a shopping purchase and deduct from user's budget
    
    Flow:
    1. Check user's budget
    2. Allow purchase even if it causes negative balance (overspend)
    3. Deduct amount from budget
    4. If balance goes negative, notify manager and block future purchases
    5. Record spending event
    """
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(req.user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Security: User can only shop for themselves or their subordinates
        if req.user_id != ctx.user_id and req.user_id not in ctx.manager_of:
            raise HTTPException(status_code=403, detail="Cannot shop for this user")
        
        # Get user's cost centre budget
        user_cc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(req.user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id)
        ).with_for_update().first()
        
        if not user_cc:
            raise HTTPException(status_code=404, detail="User not assigned to cost centre")
        
        # Check current balance
        current_balance = user_cc.allocated_budget_minor - user_cc.spent_minor
        
        # Check if user is already blocked (negative balance from previous overspend)
        if current_balance < 0 and not req.force_allow:
            raise HTTPException(
                status_code=403,
                detail=f"Shopping blocked - negative balance: £{current_balance / 100:.2f}. Please request additional budget."
            )
        
        # Calculate new balance after purchase
        new_balance = current_balance - req.amount_minor
        is_overspend = new_balance < 0
        
        # Update spent amount (allow overspend on first occurrence)
        user_cc.spent_minor += req.amount_minor
        
        # Record spending event
        spending_event = SpendingEvent(
            event_id=uuid.uuid4(),
            event_type="purchase",
            user_id=uuid.UUID(req.user_id),
            cost_centre_id=uuid.UUID(req.cost_centre_id),
            order_id=uuid.UUID(req.order_id) if req.order_id else None,
            approval_request_id=None,
            amount_minor=req.amount_minor,
            currency_code=req.currency or user_cc.currency_code,
            event_metadata={
                "description": req.description,
                "is_overspend": is_overspend,
                "balance_before": current_balance,
                "balance_after": new_balance
            }
        )
        db.add(spending_event)
        
        db.commit()
        db.refresh(user_cc)
        
        logger.info(f"✅ Purchase recorded: £{req.amount_minor / 100:.2f} by user {req.user_id}")
        
        # Notify manager if overspend
        if is_overspend:
            logger.warning(f"⚠️  OVERSPEND: User {req.user_id} went negative by £{abs(new_balance) / 100:.2f}")
            # Schedule background notification
            if ctx.manager_of:  # If user has a manager
                # Find manager ID (in practice, would query org_units)
                bg.add_task(notify_manager_overspend, req.user_id, "manager_placeholder", abs(new_balance))
        
        return ShoppingResponse(
            event_id=str(spending_event.event_id),
            user_id=req.user_id,
            amount_minor=req.amount_minor,
            allocated_budget_minor=user_cc.allocated_budget_minor,
            spent_minor=user_cc.spent_minor,
            remaining_minor=user_cc.allocated_budget_minor - user_cc.spent_minor,
            is_overspend=is_overspend,
            blocked_from_shopping=is_overspend,  # Block if negative
            message="Purchase successful" if not is_overspend else "Purchase allowed but budget exceeded - shopping blocked until budget request approved"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Shopping purchase failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/budget-status/{user_id}")
async def get_budget_status(
    user_id: str,
    cost_centre_id: Optional[str] = None,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_user_context)
):
    """Get user's shopping budget status (available, blocked, etc.)"""
    try:
        # Security check
        if user_id != ctx.user_id and user_id not in ctx.manager_of:
            raise HTTPException(status_code=403, detail="Cannot view this user's budget")
        
        user_cc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id)
        )
        if cost_centre_id:
            user_cc = user_cc.filter(UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id))
        
        user_cc = user_cc.first()
        
        if not user_cc:
            raise HTTPException(status_code=404, detail="User cost centre assignment not found")
        
        remaining = user_cc.allocated_budget_minor - user_cc.spent_minor
        is_blocked = remaining < 0
        
        return {
            "user_id": user_id,
            "cost_centre_id": str(user_cc.cost_centre_id),
            "allocated_budget_minor": user_cc.allocated_budget_minor,
            "spent_minor": user_cc.spent_minor,
            "remaining_minor": remaining,
            "is_blocked": is_blocked,
            "can_shop": not is_blocked,
            "overspend_amount": abs(remaining) if is_blocked else 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Budget status check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

