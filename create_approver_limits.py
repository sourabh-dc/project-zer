#!/usr/bin/env python3
"""
Direct database script to create approver limits
Workaround for the /approver-limits endpoint 404 issue
"""
import uuid
from datetime import date
from core.db_config import SessionLocal
from Models import ApproverLimit, User, CostCentre
from utils.logger import logger

def create_approver_limit(user_id: str, cost_centre_id: str, tenant_id: str, 
                          daily_limit_minor: int = 50000, monthly_limit_minor: int = 500000):
    """Create approver limit directly in database"""
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
        
        # Check if limit already exists
        existing = db.query(ApproverLimit).filter(
            ApproverLimit.user_id == uuid.UUID(user_id),
            ApproverLimit.tenant_id == uuid.UUID(tenant_id),
            ApproverLimit.cost_centre_id == uuid.UUID(cost_centre_id)
        ).first()
        
        if existing:
            # Update existing
            existing.daily_limit_minor = daily_limit_minor
            existing.monthly_limit_minor = monthly_limit_minor
            existing.last_reset_daily = date.today()
            logger.info(f"✅ Updated approver limit for user {user_id}")
        else:
            # Create new
            limit = ApproverLimit(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(tenant_id),
                user_id=uuid.UUID(user_id),
                cost_centre_id=uuid.UUID(cost_centre_id),
                daily_limit_minor=daily_limit_minor,
                monthly_limit_minor=monthly_limit_minor,
                daily_spent_minor=0,
                monthly_spent_minor=0,
                last_reset_daily=date.today(),
                currency_code="INR"
            )
            db.add(limit)
            logger.info(f"✅ Created approver limit for user {user_id}")
        
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to create approver limit: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python create_approver_limits.py <user_id> <cost_centre_id> <tenant_id> [daily_limit] [monthly_limit]")
        sys.exit(1)
    
    user_id = sys.argv[1]
    cost_centre_id = sys.argv[2]
    tenant_id = sys.argv[3]
    daily_limit = int(sys.argv[4]) if len(sys.argv) > 4 else 50000
    monthly_limit = int(sys.argv[5]) if len(sys.argv) > 5 else 500000
    
    try:
        create_approver_limit(user_id, cost_centre_id, tenant_id, daily_limit, monthly_limit)
        print(f"✅ Successfully created/updated approver limit")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

