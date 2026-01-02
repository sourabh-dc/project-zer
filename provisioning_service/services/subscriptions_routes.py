from datetime import datetime, timezone, timedelta
from typing import Optional, List
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import SubscriptionPlan, TenantSubscription, Tenant, User, UserRole, Role, \
    PlanPrice, Feature, PlanFeature, RolePermission, Permission
from provisioning_service.Schemas import TenantSubscriptionRequest, CurrentSubscriptionResponse, \
    CancelSubscriptionRequest, TenantSubscriptionUpgradeRequest, UpgradePreviewResponse, UserContext
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/subscriptions", tags=["Subscription Plans"])

TRIAL_DAYS = 7


class SubscribeRequest(BaseModel):
    """Request to subscribe to a plan"""
    plan_code: str = Field(description="Plan code to subscribe to")
    billing_cycle: str = Field(default="monthly", description="monthly, quarterly, or yearly")
    start_trial: bool = Field(default=True, description="Start with 7-day free trial")


class WhoAmIResponse(BaseModel):
    """Current user context with tenant and subscription info"""
    user_id: str
    email: str
    display_name: Optional[str]
    tenant_id: str
    tenant_name: str
    roles: List[str]
    permissions: List[str]
    subscription: Optional[dict] = None
    plan: Optional[dict] = None
    features: List[dict] = []
    trial_info: Optional[dict] = None


@router.get("/whoami")
async def whoami(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("tenant.admin"))
):
    """
    Get current user's complete context including:
    - User details
    - Tenant details
    - Active subscription
    - Plan details with pricing
    - Enabled features
    - Trial status
    """
    user_id = uuid.UUID(ctx["user_id"]) if isinstance(ctx, dict) else uuid.UUID(ctx.user_id)
    tenant_id = uuid.UUID(ctx["tenant_id"]) if isinstance(ctx, dict) else uuid.UUID(ctx.tenant_id)

    # Get user
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    # Get tenant
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # Get roles
    user_roles = db.query(Role.code).join(
        UserRole, UserRole.role_id == Role.role_id
    ).filter(UserRole.user_id == user_id).all()
    roles = [r[0] for r in user_roles]

    # Get permissions from roles
    permissions = []
    for role_code in roles:
        role_perms = db.query(Permission.code).join(
            RolePermission, RolePermission.permission_code == Permission.code
        ).filter(RolePermission.role_code == role_code).all()
        permissions.extend([p[0] for p in role_perms])
    permissions = list(set(permissions))

    # Get active subscription
    now = datetime.now(timezone.utc)
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.is_active == True,
        TenantSubscription.current_period_end > now
    ).first()

    subscription_data = None
    plan_data = None
    features_data = []
    trial_info = None

    if sub:
        # Get plan
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == sub.plan_code).first()
        pricing = db.query(PlanPrice).filter(PlanPrice.plan_code == sub.plan_code).first()

        days_remaining = max(0, (sub.current_period_end - now).days) if sub.current_period_end else 0

        subscription_data = {
            "id": sub.id,
            "plan_code": sub.plan_code,
            "billing_cycle": sub.billing_cycle,
            "is_active": sub.is_active,
            "is_trial": sub.is_trial,
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "days_remaining": days_remaining,
            "payment_method": sub.payment_method,
        }

        if plan:
            plan_data = {
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
            }
            if pricing:
                plan_data["pricing"] = {
                    "currency": pricing.currency,
                    "monthly": int(pricing.price_monthly_minor),
                    "quarterly": int(pricing.price_quarterly_minor),
                    "yearly": int(pricing.price_yearly_minor),
                }

        # Get features
        plan_features = db.query(Feature, PlanFeature).join(
            PlanFeature, PlanFeature.feature_code == Feature.code
        ).filter(
            PlanFeature.plan_code == sub.plan_code,
            PlanFeature.enabled == True,
            Feature.active == True
        ).all()

        features_data = []
        for f, pf in plan_features:
            limit = None
            if pf.limits and isinstance(pf.limits, dict):
                mv = pf.limits.get("max_value")
                if mv is not None:
                    try:
                        limit = int(mv)
                    except ValueError:
                        limit = None
            if limit is None and f.max_unit:
                limit = f.max_unit

            features_data.append({
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "usage_type": f.usage_type,
                "max_unit": limit,
                "reset_period": f.reset_period,
                "limits": pf.limits
            })

        if sub.is_trial:
            trial_info = {
                "is_trial": True,
                "trial_ends": sub.current_period_end.isoformat() if sub.current_period_end else None,
                "days_left": days_remaining,
            }

    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "display_name": user.display_name,
        "tenant_id": str(tenant.tenant_id),
        "tenant_name": tenant.tenant_name,
        "roles": roles,
        "permissions": permissions,
        "subscription": subscription_data,
        "plan": plan_data,
        "features": features_data,
        "trial_info": trial_info,
    }


@router.post("/subscribe", status_code=201)
async def subscribe_to_plan(
    req: SubscribeRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("tenant.admin"))
):
    """
    Subscribe tenant to a plan. Includes 7-day free trial by default.
    After trial, subscription continues with the selected billing cycle.
    """
    tenant_id = uuid.UUID(ctx["tenant_id"]) if isinstance(ctx, dict) else uuid.UUID(ctx.tenant_id)

    # Check plan exists
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.code == req.plan_code,
        SubscriptionPlan.is_active == True
    ).first()
    if not plan:
        raise HTTPException(404, "Plan not found or inactive")

    # Check for existing active subscription
    now = datetime.now(timezone.utc)
    existing = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.is_active == True,
        TenantSubscription.current_period_end > now
    ).first()

    if existing:
        raise HTTPException(400, f"Active subscription exists (plan: {existing.plan_code}). Cancel or upgrade instead.")

    # Deactivate any old subscriptions
    db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).update({"is_active": False})

    # Calculate period
    if req.start_trial:
        period_start = now
        period_end = now + timedelta(days=TRIAL_DAYS)
        is_trial = True
    else:
        period_start = now
        if req.billing_cycle == "yearly":
            period_end = now + timedelta(days=365)
        elif req.billing_cycle == "quarterly":
            period_end = now + timedelta(days=90)
        else:
            period_end = now + timedelta(days=30)
        is_trial = False

    # Create subscription
    subscription = TenantSubscription(
        tenant_id=tenant_id,
        plan_code=req.plan_code,
        billing_cycle=req.billing_cycle,
        payment_method="pending",
        current_period_start=period_start,
        current_period_end=period_end,
        is_active=True,
        is_trial=is_trial,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    # Get pricing
    pricing = db.query(PlanPrice).filter(PlanPrice.plan_code == req.plan_code).first()
    price = 0
    if pricing:
        if req.billing_cycle == "yearly":
            price = int(pricing.price_yearly_minor)
        elif req.billing_cycle == "quarterly":
            price = int(pricing.price_quarterly_minor)
        else:
            price = int(pricing.price_monthly_minor)

    logger.info(f"Subscription created: tenant={tenant_id}, plan={req.plan_code}, trial={is_trial}")

    return {
        "subscription_id": subscription.id,
        "tenant_id": str(tenant_id),
        "plan_code": req.plan_code,
        "plan_name": plan.name,
        "billing_cycle": req.billing_cycle,
        "is_trial": is_trial,
        "trial_days": TRIAL_DAYS if is_trial else 0,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "price_minor": 0 if is_trial else price,
        "currency": pricing.currency if pricing else "GBP",
        "message": f"{'7-day free trial started!' if is_trial else 'Subscription active.'} Ends {period_end.strftime('%Y-%m-%d')}",
    }


@router.post("/create", status_code=201)
async def create_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Create a new subscription"""
    tenant_subscription = TenantSubscription(tenant_id=req.tenant_id, plan_code=req.plan_code,
                                             current_period_start=req.current_period_start, is_trial=False,
                                             current_period_end=req.current_period_end, payment_method=req.payment_method,
                                             is_active=True, external_id=req.external_id)

    db.add(tenant_subscription)
    db.commit()
    return tenant_subscription

@router.post("/renew", status_code=201)
async def renew_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Renew current subscription"""
    current_subscription = db.query(TenantSubscription).filter_by(id=req.previous_sub_id).first()
    current_subscription.is_active = False
    db.commit()

    # create a new subscription
    tenant_subscription = TenantSubscription(tenant_id=req.tenant_id, plan_code=req.plan_code,
                                             current_period_start=req.current_period_start, is_trial=False,
                                             current_period_end=req.current_period_end,
                                             payment_method=req.payment_method,
                                             is_active=True, external_id=req.external_id,
                                             previous_sub_id=req.previous_sub_id)

    db.add(tenant_subscription)
    db.commit()
    return tenant_subscription

@router.get("/upgrade-preview", response_model=UpgradePreviewResponse)
async def upgrade_preview(
    req: TenantSubscriptionUpgradeRequest,
    db: Session = Depends(get_db)
):
    """Check the current subscription balance and calculate prorated upgrade cost"""

    # 1. Fetch current subscription
    subscription = db.query(TenantSubscription).filter(
        TenantSubscription.id == req.subscription_id,
        TenantSubscription.tenant_id == req.tenant_id
    ).first()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # 2. Fetch current and new plan
    current_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == subscription.plan_code).first()
    new_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.upgrade_plan_code).first()

    if not current_plan or not new_plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    # 3. Calculate prorated difference
    now = datetime.utcnow()
    if not subscription.current_period_end or now >= subscription.current_period_end:
        raise HTTPException(status_code=400, detail="Subscription already expired")

    total_days = (subscription.current_period_end - subscription.current_period_start).days
    remaining_days = (subscription.current_period_end - now).days

    current_billing_cycle = subscription.billing_cycle or 'monthly'
    if current_billing_cycle == 'monthly':
        daily_delta = (new_plan.price_monthly_minor - current_plan.price_monthly_minor) / total_days
        prorated_amount = round(daily_delta * remaining_days, 2)
        return UpgradePreviewResponse(
            current_plan=current_plan.code,
            new_plan=new_plan.code,
            remaining_days=remaining_days,
            prorated_amount=max(prorated_amount, 0.0),
            next_cycle_amount=new_plan.price_monthly_minor
        )
    else:
        daily_delta = (new_plan.price_yearly_minor - current_plan.price_yearly_minor) / total_days
        prorated_amount = round(daily_delta * remaining_days, 2)
        return UpgradePreviewResponse(
            current_plan=current_plan.code,
            new_plan=new_plan.code,
            remaining_days=remaining_days,
            prorated_amount=max(prorated_amount, 0.0),
            next_cycle_amount=new_plan.price_yearly_minor
        )


@router.get("/upgrade")
async def upgrade_current_subscription(req: TenantSubscriptionRequest,db: Session = Depends(get_db)):
    """Upgrade the current subscription to a new plan"""

    # Update current subscription status and end date
    current_subscription = db.query(TenantSubscription).filter_by(id=req.previous_sub_id).first()
    current_subscription.is_active = False
    current_subscription.current_period_end = datetime.now(timezone.utc)
    db.commit()

    # create a new subscription
    tenant_subscription = TenantSubscription(tenant_id=req.tenant_id, plan_code=req.plan_code,
                                             current_period_start=datetime.now(), is_trial=False,
                                             current_period_end=req.current_period_end, payment_method=req.payment_method,
                                             is_active=True, external_id=req.external_id, previous_sub_id=req.previous_sub_id)

    db.add(tenant_subscription)
    db.commit()
    return tenant_subscription

@router.get("/downgrade")
async def upgrade_current_subscription(req: TenantSubscriptionRequest,db: Session = Depends(get_db)):
    """Downgrade the current subscription to a new plan"""

    # Update current subscription status and end date
    current_subscription = db.query(TenantSubscription).filter_by(id=req.previous_sub_id).first()
    current_subscription.is_active = False
    db.commit()

    # create a new subscription
    tenant_subscription = TenantSubscription(tenant_id=req.tenant_id, plan_code=req.plan_code,
                                             current_period_start=current_subscription.current_period_end, is_trial=False,
                                             current_period_end=req.current_period_end, payment_method=req.payment_method,
                                             is_active=True, external_id=req.external_id, previous_sub_id=req.previous_sub_id)

    db.add(tenant_subscription)
    db.commit()
    return tenant_subscription

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
    plan = db.query(SubscriptionPlan).filter_by(code=sub.plan_code).first()
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
    
    return CurrentSubscriptionResponse(
        tenant_id=str(sub.tenant_id),
        plan_code=str(sub.plan_code),
        plan_name=plan_name,
        is_active=bool(sub.is_active),
        current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        on_trial=bool(on_trial),
        days_remaining=days_remaining
    )

@router.post("/cancel")
async def cancel_subscription(
    req: CancelSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """Cancel subscription"""
    sub = db.query(TenantSubscription).filter_by(id=req.subscription_id).first()
    
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
    logger.info(f"Canceled subscription for tenant {req.tenant_id}")
    
    return {
        "tenant_id": str(req.tenant_id),
        "status": "Cancelled",
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "message": message
    }
