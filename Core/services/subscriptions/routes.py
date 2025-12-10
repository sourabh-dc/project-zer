from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid

from Models import TenantSubscription, PlanCatalog, PlanPriceCatalog
from Schemas import TenantSubscriptionRequest, CurrentSubscriptionResponse, \
    CancelSubscriptionRequest, TenantSubscriptionUpgradeRequest, UpgradePreviewResponse, UserContext
from core.db_config import get_db
from utils.logger import logger
from core.permission_check_helpers import require_permission
from core.user_auth import get_user_context


router = APIRouter(prefix="/subscriptions", tags=["Subscription Plans"])

# ============================================================================
# Tenant Subscription Management
# ============================================================================

@router.post("/create", status_code=201)
async def create_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Create a new subscription with a 7-day trial."""
    # Ensure caller belongs to tenant
    if ctx.tenant_id and str(ctx.tenant_id) != str(req.tenant_id):
        raise HTTPException(status_code=403, detail="Tenant mismatch")

    plan_code = req.plan_selected.lower()
    plan = db.query(PlanCatalog).filter(PlanCatalog.code == plan_code).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    price = db.query(PlanPriceCatalog).filter(PlanPriceCatalog.plan_code == plan_code).first()
    if not price:
        raise HTTPException(status_code=400, detail="Price not configured for this plan")

    billing_cycle = req.billing_cycle or "monthly"
    if billing_cycle not in {"monthly", "quarterly", "yearly"}:
        raise HTTPException(status_code=400, detail="Invalid billing_cycle; must be monthly, quarterly, or yearly")

    if billing_cycle == "monthly":
        amount_minor = price.price_monthly_minor
    elif billing_cycle == "quarterly":
        amount_minor = price.price_quarterly_minor
    else:
        amount_minor = price.price_yearly_minor

    trial_start = datetime.now(timezone.utc)
    trial_end = trial_start + timedelta(days=7)

    existing = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == req.tenant_id).first()
    created_by_uuid = None
    created_by_source = req.created_by or ctx.user_id
    if created_by_source:
        try:
            created_by_uuid = uuid.UUID(str(created_by_source))
        except Exception:
            logger.warning(f"created_by is not a valid UUID; storing as NULL. value={created_by_source}")

    if existing:
        existing.plan_selected = plan_code
        existing.billing_cycle = billing_cycle
        existing.payment_method = req.payment_method
        existing.is_active = True
        existing.status = "active"
        existing.created_by = created_by_uuid
        existing.currency = price.currency
        existing.price_minor = amount_minor
        # do not reset trials for existing subscriptions; extend if not set
        if not existing.trial_start:
            existing.trial_start = trial_start
            existing.trial_end = trial_end
            existing.is_trial = True
        if not existing.current_period_start:
            existing.current_period_start = trial_start
            existing.current_period_end = trial_end
        # update price references if needed
        db.commit()
        db.refresh(existing)
        return existing

    tenant_subscription = TenantSubscription(
        tenant_subscription_id=uuid.uuid4(),
        tenant_id=req.tenant_id,
        plan_selected=plan_code,
        billing_cycle=billing_cycle,
        payment_method=req.payment_method,
        status="active",
        currency=price.currency,
        price_minor=amount_minor,
        current_period_start=trial_start,
        current_period_end=trial_end,
        trial_start=trial_start,
        trial_end=trial_end,
        is_trial=True,
        is_active=True,
        created_by=created_by_uuid,
    )

    db.add(tenant_subscription)
    db.commit()
    db.refresh(tenant_subscription)
    return tenant_subscription

@router.post("/renew", status_code=400)
async def renew_subscription():
    raise HTTPException(status_code=400, detail="Renew endpoint not implemented for new schema")

@router.get("/upgrade-preview", status_code=400)
async def upgrade_preview():
    raise HTTPException(status_code=400, detail="Upgrade preview not implemented for new schema")


@router.get("/upgrade", status_code=400)
async def upgrade_current_subscription():
    raise HTTPException(status_code=400, detail="Upgrade endpoint not implemented for new schema")

@router.get("/downgrade", status_code=400)
async def downgrade_current_subscription():
    raise HTTPException(status_code=400, detail="Downgrade endpoint not implemented for new schema")

@router.get("/active", response_model=CurrentSubscriptionResponse)
async def get_current_subscription(
    db: Session = Depends(get_db),
    tenant_id: Optional[str] = None,
):
    """Get current tenant's subscription status"""
    now = datetime.now(timezone.utc)
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.is_active == True,
        TenantSubscription.current_period_end > now
    ).first()
    
    if not sub:
        return CurrentSubscriptionResponse(
            tenant_id=str(tenant_id),
            plan_code=None,
            plan_name=None,
            status="No Active Subscription",
            on_trial=False
        )
    
    # Get plan details
    plan = db.query(PlanCatalog).filter_by(code=sub.plan_selected).first()
    plan_name = plan.name if plan else None
    
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
    
    resp = CurrentSubscriptionResponse(
        tenant_id=str(sub.tenant_id),
        plan_code=str(sub.plan_selected),
        plan_name=plan_name,
        is_active=bool(sub.is_active),
        current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        on_trial=bool(on_trial),
        days_remaining=days_remaining,
        price_minor=sub.price_minor,
        currency=sub.currency
    )
    return resp


@router.get("/{tenant_id}", response_model=CurrentSubscriptionResponse)
async def get_subscription_by_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    plan = db.query(PlanCatalog).filter_by(code=sub.plan_selected).first()
    now = datetime.now(timezone.utc)
    on_trial = (
        sub.is_trial and
        sub.current_period_end and
        sub.current_period_end > now
    )
    days_remaining = None
    if sub.current_period_end:
        delta = sub.current_period_end - now
        days_remaining = max(0, delta.days)
    return CurrentSubscriptionResponse(
        tenant_id=str(sub.tenant_id),
        plan_code=sub.plan_selected,
        plan_name=plan.name if plan else None,
        is_active=bool(sub.is_active),
        status=sub.status,
        current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        on_trial=on_trial,
        days_remaining=days_remaining,
        price_minor=sub.price_minor,
        currency=sub.currency
    )


@router.get("/", response_model=list[CurrentSubscriptionResponse])
async def list_subscriptions(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0
):
    subs = db.query(TenantSubscription).order_by(TenantSubscription.created_at.desc()).offset(offset).limit(limit).all()
    now = datetime.now(timezone.utc)
    results = []
    for sub in subs:
        plan = db.query(PlanCatalog).filter_by(code=sub.plan_selected).first()
        on_trial = sub.is_trial and sub.current_period_end and sub.current_period_end > now
        days_remaining = None
        if sub.current_period_end:
            delta = sub.current_period_end - now
            days_remaining = max(0, delta.days)
        results.append(CurrentSubscriptionResponse(
            tenant_id=str(sub.tenant_id),
            plan_code=sub.plan_selected,
            plan_name=plan.name if plan else None,
            is_active=bool(sub.is_active),
            status=sub.status,
            current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
            current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
            on_trial=on_trial,
            days_remaining=days_remaining,
            price_minor=sub.price_minor,
            currency=sub.currency
        ))
    return results

@router.post("/cancel")
async def cancel_subscription(
    req: CancelSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Cancel subscription"""
    sub = db.query(TenantSubscription).filter_by(tenant_subscription_id=req.subscription_id).first()
    
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
    logger.info(f"✅ Canceled subscription for tenant {req.tenant_id}")
    
    return {
        "tenant_id": str(req.tenant_id),
        "status": "Cancelled",
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "message": message
    }
