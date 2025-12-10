#!/usr/bin/env python3
"""
Direct database script to create instant budget request
Workaround for the /request endpoint 404 issue
"""
import uuid
from datetime import datetime, timezone, timedelta
from core.db_config import SessionLocal
from Models import InstantBudgetRequest, User, CostCentre, UserCostCentre
from utils.logger import logger

def create_instant_request(user_id: str, cost_centre_id: str, tenant_id: str,
                          amount_minor: int, reason: str = "Customer waiting"):
    """Create instant budget request directly in database"""
    db = SessionLocal()
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise ValueError(f"User not found: {user_id}")
        
        # Verify cost centre exists
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise ValueError(f"Cost centre not found: {cost_centre_id}")
        
        # Verify user is assigned to cost centre
        user_cc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id)
        ).first()
        
        if not user_cc:
            raise ValueError(f"User not assigned to cost centre")
        
        # Create request
        request = InstantBudgetRequest(
            request_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            user_id=uuid.UUID(user_id),
            cost_centre_id=uuid.UUID(cost_centre_id),
            store_id=None,
            requested_amount_minor=amount_minor,
            approved_amount_minor=0,
            remaining_amount_minor=amount_minor,
            status="pending",
            reason=reason,
            requested_by=uuid.UUID(user_id),
            approved_by=None,
            approved_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=3)
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        
        logger.info(f"✅ Created instant budget request {request.request_id} for user {user_id}")
        
        return {
            "request_id": str(request.request_id),
            "status": request.status,
            "expires_at": request.expires_at.isoformat(),
            "approved_amount_minor": request.approved_amount_minor,
            "remaining_amount_minor": request.remaining_amount_minor
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to create instant request: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 5:
        print("Usage: python create_instant_request.py <user_id> <cost_centre_id> <tenant_id> <amount_minor> [reason]")
        sys.exit(1)
    
    user_id = sys.argv[1]
    cost_centre_id = sys.argv[2]
    tenant_id = sys.argv[3]
    amount_minor = int(sys.argv[4])
    reason = sys.argv[5] if len(sys.argv) > 5 else "Customer waiting"
    
    try:
        result = create_instant_request(user_id, cost_centre_id, tenant_id, amount_minor, reason)
        print(f"✅ Successfully created instant budget request")
        print(f"   Request ID: {result['request_id']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

