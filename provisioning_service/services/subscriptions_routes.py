from datetime import datetime, timezone, timedelta
from typing import Optional, List
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import SubscriptionPlan, TenantSubscription, Tenant, User, UserIdentity, UserRole, Role, \
    PlanPrice, Feature, PlanFeature, RolePermission, Permission
from provisioning_service.Schemas import TenantSubscriptionRequest, CurrentSubscriptionResponse, \
    CancelSubscriptionRequest, TenantSubscriptionUpgradeRequest, UpgradePreviewResponse, UserContext, SubscribeRequest, \
    ChangePlanCheckRequest, ChangePlanCheckResponse, PlanViolation, ChangePlanRequest, ChangePlanResponse
from provisioning_service.core.db_config import get_db
from provisioning_service.core.entitlement_helpers import plan_change_violations
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger


router = APIRouter(prefix="/subscriptions", tags=["Subscription Plans"])

TRIAL_DAYS = 7

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

    # Get user identity (contains email, auth info)
    user_identity = db.query(UserIdentity).filter(UserIdentity.user_id == user_id).first()

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
            "pending_plan_code": sub.pending_plan_code,
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
        "email": user_identity.email if user_identity else None,
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

@router.post("/renew", status_code=201)
async def renew_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscription.manage")),
    policy=Depends(require_policy("subscription.renew")),
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

    # Outbox audit event
    try:
        create_outbox_event(db, req.tenant_id, "subscription.renewed", {
            "subscription_id": str(tenant_subscription.id),
            "tenant_id": str(req.tenant_id),
            "plan_code": req.plan_code,
            "previous_sub_id": str(req.previous_sub_id),
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for subscription.renewed: {_oe}")

    return tenant_subscription

@router.post("/upgrade-preview", response_model=UpgradePreviewResponse)
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

    # 2. Prices live in PlanPrice — not on SubscriptionPlan
    current_price = db.query(PlanPrice).filter(PlanPrice.plan_code == subscription.plan_code).first()
    new_price = db.query(PlanPrice).filter(PlanPrice.plan_code == req.upgrade_plan_code).first()
    new_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.upgrade_plan_code).first()

    if not current_price or not new_price or not new_plan:
        raise HTTPException(status_code=404, detail="Plan or price not found")

    # 3. Calculate prorated difference
    now = datetime.now(timezone.utc)
    period_end = subscription.current_period_end
    if period_end is not None and period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    if not period_end or now >= period_end:
        raise HTTPException(status_code=400, detail="Subscription already expired")

    period_start = subscription.current_period_start
    if period_start is not None and period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    total_days = max(1, (period_end - period_start).days)
    remaining_days = max(0, (period_end - now).days)

    current_billing_cycle = subscription.billing_cycle or 'monthly'
    if current_billing_cycle == 'yearly':
        current_amount, new_amount = current_price.price_yearly_minor, new_price.price_yearly_minor
    elif current_billing_cycle == 'quarterly':
        current_amount, new_amount = current_price.price_quarterly_minor, new_price.price_quarterly_minor
    else:
        current_amount, new_amount = current_price.price_monthly_minor, new_price.price_monthly_minor

    daily_delta = (float(new_amount) - float(current_amount)) / total_days
    prorated_amount = round(daily_delta * remaining_days, 2)
    return UpgradePreviewResponse(
        current_plan=subscription.plan_code,
        new_plan=new_plan.code,
        remaining_days=remaining_days,
        prorated_amount=max(prorated_amount, 0.0),
        next_cycle_amount=float(new_amount)
    )


# ── Plan change (upgrade / downgrade) ───────────────────────────────

def _plan_monthly(db: Session, plan_code: str) -> float:
    price = db.query(PlanPrice).filter(PlanPrice.plan_code == plan_code).first()
    return float(price.price_monthly_minor or 0) if price else 0.0


def _active_sub_for_tenant(db: Session, tenant_id: str) -> TenantSubscription:
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.is_active == True,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")
    return sub


@router.post("/change-plan/check", response_model=ChangePlanCheckResponse)
async def change_plan_check(
    req: ChangePlanCheckRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscription.manage")),
):
    """Dry-run: compare current real usage against the target plan's limits."""
    tenant_id = str(ctx.get("tenant_id"))
    sub = _active_sub_for_tenant(db, tenant_id)

    target = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.code == req.target_plan_code,
        SubscriptionPlan.is_active == True,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target plan not found")

    current_m = _plan_monthly(db, sub.plan_code)
    target_m = _plan_monthly(db, req.target_plan_code)
    direction = "upgrade" if target_m > current_m else ("downgrade" if target_m < current_m else "lateral")

    violations = plan_change_violations(db, tenant_id, req.target_plan_code)
    return ChangePlanCheckResponse(
        current_plan=sub.plan_code,
        target_plan=req.target_plan_code,
        direction=direction,
        allowed=len(violations) == 0,
        violations=[PlanViolation(**v) for v in violations],
    )


@router.post("/change-plan", response_model=ChangePlanResponse)
async def change_plan(
    req: ChangePlanRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscription.manage")),
):
    """
    Switch plan.

    - Upgrade (higher price): applies immediately — features/limits switch now.
    - Downgrade: validated against real usage; scheduled at period end via
      ``pending_plan_code`` so the tenant keeps what it paid for.
    """
    tenant_id = str(ctx.get("tenant_id"))
    sub = _active_sub_for_tenant(db, tenant_id)

    if req.target_plan_code == sub.plan_code:
        raise HTTPException(status_code=400, detail="Already on this plan")

    target = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.code == req.target_plan_code,
        SubscriptionPlan.is_active == True,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target plan not found")

    current_m = _plan_monthly(db, sub.plan_code)
    target_m = _plan_monthly(db, req.target_plan_code)
    is_upgrade = target_m > current_m
    now = datetime.now(timezone.utc)

    if is_upgrade:
        # Immediate: plan_code drives load_tenant_features(), so features
        # and limits switch on next request.
        old_plan = sub.plan_code
        sub.plan_code = req.target_plan_code
        sub.pending_plan_code = None
        db.commit()

        # Best-effort prorated charge for the remainder of the period
        prorated = None
        try:
            period_end = sub.current_period_end
            if period_end and period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=timezone.utc)
            period_start = sub.current_period_start
            if period_start and period_start.tzinfo is None:
                period_start = period_start.replace(tzinfo=timezone.utc)
            if period_end and period_start and period_end > now:
                total_days = max(1, (period_end - period_start).days)
                remaining_days = max(0, (period_end - now).days)
                prorated = round((target_m - current_m) / total_days * remaining_days, 2)
        except Exception:
            prorated = None

        try:
            create_outbox_event(db, tenant_id, "subscription.upgraded", {
                "subscription_id": str(sub.id),
                "tenant_id": tenant_id,
                "from_plan": old_plan,
                "plan_code": req.target_plan_code,
                "prorated_amount": prorated,
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for subscription.upgraded: {_oe}")

        logger.info(f"Plan upgraded immediately: tenant={tenant_id} {old_plan} → {req.target_plan_code}")
        return ChangePlanResponse(
            status="upgraded",
            current_plan=old_plan,
            target_plan=req.target_plan_code,
            effective_at=now.isoformat(),
            prorated_amount=prorated,
            message="Plan upgraded — new features and limits are active now.",
        )

    # ── Downgrade: validate usage, then schedule at period end ──
    violations = plan_change_violations(db, tenant_id, req.target_plan_code)
    if violations and not req.force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Current usage exceeds the target plan's limits",
                "violations": violations,
                "hint": "Reduce usage or retry with force=true",
            },
        )

    sub.pending_plan_code = req.target_plan_code
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "subscription.downgrade_scheduled", {
            "subscription_id": str(sub.id),
            "tenant_id": tenant_id,
            "from_plan": sub.plan_code,
            "plan_code": req.target_plan_code,
            "effective_at": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "forced": req.force,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for subscription.downgrade_scheduled: {_oe}")

    logger.info(
        f"Downgrade scheduled: tenant={tenant_id} {sub.plan_code} → {req.target_plan_code} "
        f"at {sub.current_period_end}"
    )
    return ChangePlanResponse(
        status="downgrade_scheduled",
        current_plan=sub.plan_code,
        target_plan=req.target_plan_code,
        effective_at=sub.current_period_end.isoformat() if sub.current_period_end else None,
        pending_plan_code=req.target_plan_code,
        message="Downgrade scheduled — takes effect at the end of the current billing period.",
    )


@router.post("/change-plan/cancel-pending", status_code=200)
async def cancel_pending_plan_change(
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscription.manage")),
):
    """Cancel a scheduled downgrade before it takes effect."""
    tenant_id = str(ctx.get("tenant_id"))
    sub = _active_sub_for_tenant(db, tenant_id)
    if not sub.pending_plan_code:
        raise HTTPException(status_code=404, detail="No pending plan change")
    pending = sub.pending_plan_code
    sub.pending_plan_code = None
    db.commit()
    logger.info(f"Pending plan change cancelled: tenant={tenant_id} (was → {pending})")
    return {"status": "cancelled", "pending_plan_code": pending}


def apply_due_plan_changes(db: Session) -> int:
    """
    Apply scheduled downgrades whose period has ended.

    Called by the daily scheduler sweep (and safe to call from webhooks).
    For non-Stripe (dev) subscriptions the period is rolled forward here;
    Stripe-billed tenants get the new plan via the invoice.paid webhook.
    """
    now = datetime.now(timezone.utc)
    due = db.query(TenantSubscription).filter(
        TenantSubscription.pending_plan_code.isnot(None),
        TenantSubscription.is_active == True,
        TenantSubscription.current_period_end <= now,
    ).all()

    applied = 0
    for sub in due:
        old_plan = sub.plan_code
        sub.plan_code = sub.pending_plan_code
        sub.pending_plan_code = None
        # Dev/manual subs: roll the period forward so access continues
        if not sub.external_id:
            cycle_days = {"monthly": 30, "quarterly": 90, "yearly": 365}.get(sub.billing_cycle or "monthly", 30)
            sub.current_period_start = now
            sub.current_period_end = now + timedelta(days=cycle_days)
        applied += 1
        try:
            create_outbox_event(db, str(sub.tenant_id), "subscription.downgrade_applied", {
                "subscription_id": str(sub.id),
                "tenant_id": str(sub.tenant_id),
                "from_plan": old_plan,
                "plan_code": sub.plan_code,
            })
        except Exception as _oe:
            logger.warning(f"Outbox failed for subscription.downgrade_applied: {_oe}")
        logger.info(f"Pending plan applied: tenant={sub.tenant_id} {old_plan} → {sub.plan_code}")

    if applied:
        db.commit()
    return applied


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
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscription.manage")),
    policy=Depends(require_policy("subscription.cancel")),
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
        sub.current_period_end = now
        ends_at = now
        message = "Subscription canceled immediately"
    else:
        # Keep active — access continues until current_period_end, then lapses naturally
        ends_at = sub.current_period_end
        message = f"Subscription will end on {sub.current_period_end.isoformat() if sub.current_period_end else 'period end'}"

    db.commit()
    logger.info(f"Canceled subscription for tenant {req.tenant_id}")

    # Outbox audit event
    try:
        create_outbox_event(
            db, req.tenant_id, "subscription.cancelled",
            {
                "tenant_id": str(req.tenant_id),
                "subscription_id": str(req.subscription_id),
                "cancel_immediately": req.cancel_immediately,
                "reason": req.reason,
            },
        )
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for subscription.cancelled: {_oe}")

    return {
        "tenant_id": str(req.tenant_id),
        "status": "Cancelled",
        "ends_at": ends_at.isoformat() if ends_at else None,
        "message": message
    }
