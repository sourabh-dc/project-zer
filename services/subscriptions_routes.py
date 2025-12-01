# services/core/routes/subscriptions.py
"""
Subscription Management Service
- Plan CRUD
- Feature management
- Tenant subscription lifecycle (trial, active, cancel, upgrade/downgrade)
- Current subscription status
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from dateutil.relativedelta import relativedelta

from Models import (
    SubscriptionPlan, Feature, PlanFeature, TenantSubscription, Tenant
)
from Schemas import (
    SubscriptionPlanRequest, FeatureRequest, PlanFeatureRequest,
    TenantSubscriptionRequest, UserContext, CurrentSubscriptionResponse,
    CancelSubscriptionRequest, UpgradeDowngradeRequest
)
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger

router = APIRouter(prefix="/v1/subscriptions", tags=["subscriptions"])

# Configuration
TRIAL_DAYS = 14  # Free trial period

# ============================================================================
# Tenant Subscription Management
# ============================================================================

@router.post("/create", status_code=201)
async def create_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Create a new subscription"""
    # Verify plan exists and is active
    tenant_subscription = TenantSubscription(tenant_id=req.tenant_id, plan_code=req.plan_code,
                                             current_period_start=req.current_period_start, is_trial=False,
                                             current_period_end=req.current_period_end)

    db.add(tenant_subscription)
    db.commit()
    return tenant_subscription


@router.get("/current", response_model=CurrentSubscriptionResponse)
async def get_current_subscription(
    db: Session = Depends(get_db),
    tenant_id: Optional[str] = None,
):
    """Get current tenant's subscription status"""
    sub = db.query(TenantSubscription).filter_by(tenant_id=tenant_id).first()
    
    if not sub:
        return CurrentSubscriptionResponse(
            tenant_id=str(tenant_id),
            plan_code=None,
            plan_name=None,
            status="no_subscription",
            on_trial=False
        )
    
    # Get plan details
    plan = db.query(SubscriptionPlan).filter_by(code=sub.plan_code).first()
    plan_name = plan.name if plan else None
    
    now = datetime.now(timezone.utc)
    
    # Check if currently on trial
    on_trial = (
        sub.is_trial and
        sub.current_period_end and
        sub.current_period_end > now
    )
    
    # Calculate days remaining
    days_remaining = None
    if sub.current_period_end:
        delta = sub.current_period_end - now
        days_remaining = max(0, delta.days)
    
    # Auto-update status if trial expired
    if sub.is_trial and sub.current_period_end <= now:
        sub.is_active = True  # Move to active after trial (in real system, check payment)
        db.commit()
    
    return CurrentSubscriptionResponse(
        tenant_id=str(sub.tenant_id),
        plan_code=sub.plan_code,
        plan_name=plan_name,
        is_active=sub.is_active,
        current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        on_trial=on_trial,
        days_remaining=days_remaining
    )

@router.post("/cancel")
async def cancel_subscription(
    req: CancelSubscriptionRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Cancel subscription"""
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not sub:
        raise HTTPException(404, "No subscription found")
    
    if not sub.is_active:
        raise HTTPException(400, "Subscription already canceled")
    
    now = datetime.now(timezone.utc)
    sub.canceled_at = now
    sub.cancellation_reason = req.reason
    
    if req.cancel_immediately:
        sub.is_active = False
        sub.ends_at = now
        message = "Subscription canceled immediately"
    else:
        # Subscription remains active until period end
        sub.is_active = False
        sub.ends_at = sub.current_period_end
        message = f"Subscription will end on {sub.current_period_end.isoformat() if sub.current_period_end else 'period end'}"
    
    db.commit()
    logger.info(f"✅ Canceled subscription for tenant {ctx.tenant_id}")
    
    return {
        "tenant_id": str(ctx.tenant_id),
        "status": "Cancelled",
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "message": message
    }

