#!/usr/bin/env python3
"""
Direct database script to approve instant budget request
Workaround for the /approve/{request_id} endpoint 404 issue
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import and_
from core.db_config import SessionLocal
from Models import InstantBudgetRequest, ApproverLimit, UserCostCentre, SpendingEvent, User
from utils.logger import logger

def approve_instant_request(request_id: str, approver_user_id: str, approve: bool = True, 
                           partial_amount_minor: int = None):
    """Approve instant budget request directly in database"""
    db = SessionLocal()
    try:
        # Get request with lock
        req = db.query(InstantBudgetRequest).filter(
            InstantBudgetRequest.request_id == uuid.UUID(request_id),
            InstantBudgetRequest.status == "pending"
        ).with_for_update().first()
        
        if not req:
            raise ValueError(f"Request not found or already processed: {request_id}")
        
        # Check if expired
        if req.expires_at < datetime.now(timezone.utc):
            req.status = "expired"
            db.commit()
            raise ValueError("Request expired")
        
        if not approve:
            req.status = "rejected"
            req.approved_by = uuid.UUID(approver_user_id)
            req.approved_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "rejected"}
        
        # Get approver's limit
        limit = db.query(ApproverLimit).filter(
            ApproverLimit.user_id == uuid.UUID(approver_user_id),
            ApproverLimit.tenant_id == req.tenant_id,
            and_(
                ApproverLimit.cost_centre_id == req.cost_centre_id,
                ApproverLimit.cost_centre_id.isnot(None)
            ) | ApproverLimit.cost_centre_id.is_(None)
        ).with_for_update().first()
        
        if not limit:
            raise ValueError("Approver has no limits configured")
        
        available_daily = limit.daily_limit_minor - limit.daily_spent_minor
        available_monthly = limit.monthly_limit_minor - limit.monthly_spent_minor
        
        # Determine amount to approve
        approve_amt = partial_amount_minor if partial_amount_minor is not None else req.remaining_amount_minor
        approve_amt = min(approve_amt, req.remaining_amount_minor, available_daily, available_monthly)
        
        if approve_amt <= 0:
            raise ValueError("No amount to approve or insufficient limit")
        
        # Update request
        req.approved_amount_minor += approve_amt
        req.remaining_amount_minor -= approve_amt
        
        # Deduct from manager's limits
        limit.daily_spent_minor += approve_amt
        limit.monthly_spent_minor += approve_amt
        
        # Add money to user's cost centre budget
        uc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == req.user_id,
            UserCostCentre.cost_centre_id == req.cost_centre_id
        ).with_for_update().first()
        
        if not uc:
            raise ValueError("User not assigned to cost centre")
        
        uc.allocated_budget_minor += approve_amt
        
        # Record spending event (using same structure as in instant_budget.py)
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
                "request_id": str(req.request_id),
                "approved_by": approver_user_id,
                "instant_budget": True
            }
        )
        db.add(spending_event)
        
        # Mark as approved if fully approved
        if req.remaining_amount_minor <= 0:
            req.status = "approved"
            req.approved_by = uuid.UUID(approver_user_id)
            req.approved_at = datetime.now(timezone.utc)
        else:
            req.status = "partial"
        
        db.commit()
        db.refresh(req)
        db.refresh(limit)
        db.refresh(uc)
        
        logger.info(f"✅ Approved {approve_amt} for request {request_id} by {approver_user_id}")
        
        return {
            "status": req.status,
            "approved_this_time": approve_amt,
            "total_approved": req.approved_amount_minor,
            "remaining": req.remaining_amount_minor,
            "user_budget_allocated": uc.allocated_budget_minor,
            "approver_limit_remaining": limit.daily_limit_minor - limit.daily_spent_minor
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to approve request: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python approve_instant_request.py <request_id> <approver_user_id> [approve] [partial_amount]")
        sys.exit(1)
    
    request_id = sys.argv[1]
    approver_user_id = sys.argv[2]
    approve = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else True
    partial_amount = int(sys.argv[4]) if len(sys.argv) > 4 else None
    
    try:
        result = approve_instant_request(request_id, approver_user_id, approve, partial_amount)
        print(f"✅ Successfully processed request")
        print(f"   Status: {result['status']}")
        print(f"   Approved: {result.get('approved_this_time', 0) / 100} rs")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

