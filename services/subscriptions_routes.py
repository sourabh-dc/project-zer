from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi import WebSocket, WebSocketDisconnect
import asyncio

from Models import SubscriptionPlan, TenantSubscription
from Schemas import TenantSubscriptionRequest, CurrentSubscriptionResponse, \
    CancelSubscriptionRequest, TenantSubscriptionUpgradeRequest, UpgradePreviewResponse
from core.db_config import get_db
from utils.logger import logger

router = APIRouter(prefix="/subscriptions", tags=["Subscription Plans"])

# ============================================================================
# Tenant Subscription Management
# ============================================================================

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
    logger.info(f"✅ Canceled subscription for tenant {req.tenant_id}")
    
    return {
        "tenant_id": str(req.tenant_id),
        "status": "Cancelled",
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "message": message
    }


@router.websocket("/ws/subscription-status/{tenant_id}")
async def subscription_status_websocket(
        websocket: WebSocket,
        tenant_id: str,
        db: Session = Depends(get_db)
):
    """
    WebSocket endpoint to check subscription status in real-time.
    Sends periodic updates about subscription creation/status for a tenant.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for tenant {tenant_id}")

    try:
        while True:
            # Query the current subscription status
            now = datetime.now(timezone.utc)
            subscription = db.query(TenantSubscription).filter(
                TenantSubscription.tenant_id == tenant_id,
                TenantSubscription.is_active == True,
                TenantSubscription.current_period_end > now
            ).first()

            if subscription:
                # Subscription found
                plan = db.query(SubscriptionPlan).filter_by(code=subscription.plan_code).first()

                response = {
                    "status": "active",
                    "subscription_exists": True,
                    "subscription_id": str(subscription.id),
                    "plan_code": subscription.plan_code,
                    "plan_name": plan.name if plan else None,
                    "is_active": subscription.is_active,
                    "is_trial": subscription.is_trial,
                    "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
                    "timestamp": now.isoformat()
                }
            else:
                # No active subscription
                response = {
                    "status": "no_subscription",
                    "subscription_exists": False,
                    "timestamp": now.isoformat()
                }

            # Send status to a client
            await websocket.send_json(response)

            # Wait 3 seconds before the next check
            await asyncio.sleep(3)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for tenant {tenant_id}")
    except Exception as e:
        logger.error(f"WebSocket error for tenant {tenant_id}: {e}", exc_info=True)
        await websocket.close(code=1011, reason="Internal server error")

