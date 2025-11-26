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
# Plan Management
# ============================================================================

@router.post("/plans", status_code=201)
async def create_plan(
    req: SubscriptionPlanRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Create a new subscription plan"""
    if db.query(SubscriptionPlan).filter_by(code=req.code).first():
        raise HTTPException(409, "Plan code already exists")

    plan = SubscriptionPlan(
        code=req.code,
        name=req.name,
        description=req.description or "",
        price_yearly_minor=req.price_yearly_minor,
        price_monthly_minor=req.price_monthly_minor,
        currency=req.currency or "GBP",
        active=True
    )
    db.add(plan)
    db.commit()
    
    logger.info(f"✅ Created plan: {plan.code} ({plan.name})")
    return {
        "plan_code": plan.code,
        "name": plan.name,
        "price_yearly_minor": plan.price_yearly_minor,
        "price_monthly_minor": plan.price_monthly_minor,
        "currency": plan.currency
    }


@router.get("/plans")
async def list_plans(
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.view"))
):
    """List all subscription plans"""
    q = db.query(SubscriptionPlan)
    if active is not None:
        q = q.filter(SubscriptionPlan.active == active)
    plans = q.order_by(SubscriptionPlan.name).all()
    return {
        "plans": [
            {
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "price_yearly_minor": p.price_yearly_minor,
                "price_monthly_minor": p.price_monthly_minor,
                "currency": p.currency,
                "active": p.active
            }
            for p in plans
        ],
        "total": len(plans)
    }


@router.get("/plans/{plan_code}")
async def get_plan(
    plan_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.view"))
):
    """Get a specific plan with its features"""
    plan = db.query(SubscriptionPlan).filter_by(code=plan_code).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    
    # Get plan features
    features = db.query(PlanFeature, Feature).join(
        Feature, PlanFeature.feature_code == Feature.code
    ).filter(
        PlanFeature.plan_code == plan_code,
        PlanFeature.enabled == True
    ).all()
    
    return {
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "price_yearly_minor": plan.price_yearly_minor,
        "price_monthly_minor": plan.price_monthly_minor,
        "currency": plan.currency,
        "active": plan.active,
        "features": [
            {
                "code": f.code,
                "name": f.name,
                "limits": pf.limits
            }
            for pf, f in features
        ]
    }


# ============================================================================
# Feature Management
# ============================================================================

@router.post("/features", status_code=201)
async def create_feature(
    req: FeatureRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """Create a new feature"""
    if db.query(Feature).filter_by(code=req.code).first():
        raise HTTPException(409, "Feature code already exists")

    f = Feature(
        id=uuid.uuid4(),
        code=req.code,
        name=req.name,
        description=req.description or "",
        category=req.category or "general",
        usage_type=req.usage_type or "count",
        unit=req.unit,
        reset_period=req.reset_period or "monthly",
        active=True
    )
    db.add(f)
    db.commit()
    
    logger.info(f"✅ Created feature: {f.code} ({f.name})")
    return {
        "feature_code": f.code,
        "name": f.name,
        "usage_type": f.usage_type,
        "reset_period": f.reset_period
    }


@router.get("/features")
async def list_features(
    active: Optional[bool] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """List all features"""
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if category:
        q = q.filter(Feature.category == category)
    features = q.order_by(Feature.category, Feature.name).all()
    return {
        "features": [
            {
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "usage_type": f.usage_type,
                "reset_period": f.reset_period,
                "active": f.active
            }
            for f in features
        ],
        "total": len(features)
    }


@router.put("/plans/{plan_code}/features/{feature_code}")
async def upsert_plan_feature(
    plan_code: str,
    feature_code: str,
    req: PlanFeatureRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Add or update a feature in a plan"""
    # Verify plan and feature exist
    if not db.query(SubscriptionPlan).filter_by(code=plan_code).first():
        raise HTTPException(404, "Plan not found")
    if not db.query(Feature).filter_by(code=feature_code).first():
        raise HTTPException(404, "Feature not found")
    
    pf = db.query(PlanFeature).filter_by(
        plan_code=plan_code,
        feature_code=feature_code
    ).first()
    
    if pf:
        pf.enabled = True
        pf.limits = req.limits or {}
    else:
        pf = PlanFeature(
            id=uuid.uuid4(),
            plan_code=plan_code,
            feature_code=feature_code,
            enabled=True,
            limits=req.limits or {}
        )
        db.add(pf)
    db.commit()
    
    logger.info(f"✅ Updated feature {feature_code} in plan {plan_code}")
    return {"plan_code": plan_code, "feature_code": feature_code, "limits": pf.limits, "enabled": True}


@router.delete("/plans/{plan_code}/features/{feature_code}", status_code=204)
async def remove_feature_from_plan(
    plan_code: str,
    feature_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Remove (disable) a feature from a plan"""
    pf = db.query(PlanFeature).filter_by(
        plan_code=plan_code,
        feature_code=feature_code
    ).first()
    if pf:
        pf.enabled = False
        db.commit()
        logger.info(f"✅ Disabled feature {feature_code} in plan {plan_code}")
    return None


# ============================================================================
# Tenant Subscription Management
# ============================================================================

@router.post("/tenant", status_code=201)
async def create_or_update_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Create a new subscription or update existing (upgrade/downgrade)"""
    if str(ctx.tenant_id) != req.tenant_id:
        raise HTTPException(403, "Cannot manage other tenant's subscription")

    # Check if tenant has existing subscription
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    # Verify plan exists and is active
    plan = db.query(SubscriptionPlan).filter_by(code=req.plan_code, active=True).first()
    if not plan:
        raise HTTPException(404, "Plan not found or inactive")

    now = datetime.now(timezone.utc)
    
    if sub:
        # Existing subscription - handle upgrade/downgrade
        if sub.status in ["canceled", "unpaid"]:
            raise HTTPException(400, "Cannot modify canceled/unpaid subscription. Please create a new one.")
        
        # If on trial, allow immediate plan change
        if sub.status == "trialing":
            sub.plan_code = req.plan_code
            sub.pending_plan_code = None
            logger.info(f"✅ Updated trial subscription for tenant {ctx.tenant_id} to plan {req.plan_code}")
        else:
            # Active subscription - plan change takes effect at period end
            sub.pending_plan_code = req.plan_code
            logger.info(f"✅ Scheduled plan change for tenant {ctx.tenant_id} to {req.plan_code} at period end")
        
        sub.updated_at = now
    else:
        # New subscription - start with trial
        # Calculate period using proper date math (relativedelta)
        if req.billing_cycle == "monthly":
            period_end = now + relativedelta(months=1)
        else:  # yearly
            period_end = now + relativedelta(years=1)
        
        sub = TenantSubscription(
            tenant_id=ctx.tenant_id,
            plan_code=req.plan_code,
            status="trialing",
            trial_ends_at=now + timedelta(days=TRIAL_DAYS),
            current_period_start=now,
            current_period_end=period_end,
            payment_method=req.payment_method or "card"
        )
        db.add(sub)
        logger.info(f"✅ Created new subscription for tenant {ctx.tenant_id} with {TRIAL_DAYS}-day trial")
    
    db.commit()
    
    return {
        "tenant_id": str(ctx.tenant_id),
        "plan_code": req.plan_code,
        "status": sub.status,
        "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "pending_plan_code": sub.pending_plan_code
    }


@router.get("/current", response_model=CurrentSubscriptionResponse)
async def get_current_subscription(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.tenant.view"))
):
    """Get current tenant's subscription status"""
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not sub:
        return CurrentSubscriptionResponse(
            tenant_id=str(ctx.tenant_id),
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
        sub.status == "trialing" and
        sub.trial_ends_at and
        sub.trial_ends_at > now
    )
    
    # Calculate days remaining
    days_remaining = None
    if sub.current_period_end:
        delta = sub.current_period_end - now
        days_remaining = max(0, delta.days)
    
    # Auto-update status if trial expired
    if sub.status == "trialing" and sub.trial_ends_at and sub.trial_ends_at <= now:
        sub.status = "active"  # Move to active after trial (in real system, check payment)
        db.commit()
    
    return CurrentSubscriptionResponse(
        tenant_id=str(sub.tenant_id),
        plan_code=sub.plan_code,
        plan_name=plan_name,
        status=sub.status,
        trial_ends_at=sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        pending_plan_code=sub.pending_plan_code,
        on_trial=on_trial,
        days_remaining=days_remaining
    )


@router.post("/upgrade-downgrade")
async def upgrade_or_downgrade(
    req: UpgradeDowngradeRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Upgrade or downgrade subscription plan"""
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not sub:
        raise HTTPException(404, "No subscription found")
    
    if sub.status in ["canceled", "unpaid"]:
        raise HTTPException(400, "Cannot modify canceled/unpaid subscription")
    
    # Verify new plan exists
    new_plan = db.query(SubscriptionPlan).filter_by(code=req.new_plan_code, active=True).first()
    if not new_plan:
        raise HTTPException(404, "New plan not found or inactive")
    
    if sub.plan_code == req.new_plan_code:
        raise HTTPException(400, "Already on this plan")
    
    now = datetime.now(timezone.utc)
    
    if req.apply_immediately or sub.status == "trialing":
        # Immediate switch
        old_plan = sub.plan_code
        sub.plan_code = req.new_plan_code
        sub.pending_plan_code = None
        sub.updated_at = now
        
        # Reset period for immediate upgrades
        if req.apply_immediately and sub.status == "active":
            sub.current_period_start = now
            sub.current_period_end = now + relativedelta(years=1)  # Assume yearly
        
        logger.info(f"✅ Immediate plan change for tenant {ctx.tenant_id}: {old_plan} → {req.new_plan_code}")
        message = "Plan changed immediately"
    else:
        # Schedule for period end
        sub.pending_plan_code = req.new_plan_code
        sub.updated_at = now
        logger.info(f"✅ Scheduled plan change for tenant {ctx.tenant_id} to {req.new_plan_code}")
        message = f"Plan will change to {req.new_plan_code} at period end"
    
    db.commit()
    
    return {
        "tenant_id": str(ctx.tenant_id),
        "current_plan": sub.plan_code,
        "pending_plan": sub.pending_plan_code,
        "status": sub.status,
        "message": message,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None
    }


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
    
    if sub.status == "canceled":
        raise HTTPException(400, "Subscription already canceled")
    
    now = datetime.now(timezone.utc)
    sub.canceled_at = now
    sub.cancellation_reason = req.reason
    
    if req.cancel_immediately:
        sub.status = "canceled"
        sub.ends_at = now
        message = "Subscription canceled immediately"
    else:
        # Subscription remains active until period end
        sub.status = "canceled"
        sub.ends_at = sub.current_period_end
        message = f"Subscription will end on {sub.current_period_end.isoformat() if sub.current_period_end else 'period end'}"
    
    db.commit()
    logger.info(f"✅ Canceled subscription for tenant {ctx.tenant_id}")
    
    return {
        "tenant_id": str(ctx.tenant_id),
        "status": sub.status,
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "message": message
    }


@router.post("/reactivate")
async def reactivate_subscription(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Reactivate a canceled subscription (before it ends)"""
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not sub:
        raise HTTPException(404, "No subscription found")
    
    now = datetime.now(timezone.utc)
    
    # Can only reactivate if subscription hasn't ended yet
    if sub.ends_at and sub.ends_at <= now:
        raise HTTPException(400, "Subscription has already ended. Please create a new subscription.")
    
    if sub.status != "canceled":
        raise HTTPException(400, "Subscription is not canceled")
    
    sub.status = "active"
    sub.canceled_at = None
    sub.ends_at = None
    sub.cancellation_reason = None
    sub.updated_at = now
    
    db.commit()
    logger.info(f"✅ Reactivated subscription for tenant {ctx.tenant_id}")
    
    return {
        "tenant_id": str(ctx.tenant_id),
        "status": sub.status,
        "plan_code": sub.plan_code,
        "message": "Subscription reactivated"
    }
