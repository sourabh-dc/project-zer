# ==================================================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ==================================================================================
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


from Models import Tenant, SubscriptionPlan, Feature, PlanFeature, TenantSubscription
from Schemas import UserContext, SubscriptionPlanRequest, FeatureRequest, PlanFeatureRequest, TenantSubscriptionRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from utils.logger import logger
from utils.metrics import req_total, req_duration

app = APIRouter()

@app.post("/v1/subscriptions/plans", status_code=201)
async def create_subscription_plan(
        req: SubscriptionPlanRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Create a new subscription plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_plan", status="start").inc()

        # Check if plan code exists
        existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Plan code already exists")

        # Create plan
        plan = SubscriptionPlan(
            code=req.code,
            name=req.name,
            description=req.description,
            price_yearly_minor=req.price_yearly_minor,
            currency=req.currency,
            active=True
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        req_total.labels(operation="create_plan", status="success").inc()
        req_duration.labels(operation="create_plan").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created subscription plan: {plan.id} ({plan.code})")

        return {
            "plan_id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "price_yearly_minor": plan.price_yearly_minor,
            "currency": plan.currency,
            "created_at": plan.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_plan", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        raise HTTPException(status_code=409, detail="Plan code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        logger.error(f"❌ Plan creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans")
async def list_subscription_plans(
        active: Optional[bool] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """List subscription plans"""
    q = db.query(SubscriptionPlan)
    if active is not None:
        q = q.filter(SubscriptionPlan.active == active)

    total = q.count()
    plans = q.order_by(SubscriptionPlan.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "plans": [
            {
                "plan_id": p.id,
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "price_yearly_minor": p.price_yearly_minor,
                "currency": p.currency,
                "active": p.active,
                "created_at": p.created_at.isoformat()
            }
            for p in plans
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/subscriptions/features", status_code=201)
async def create_feature(
        req: FeatureRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """Create a new feature"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_feature", status="start").inc()

        # Check if feature code exists
        existing = db.query(Feature).filter(Feature.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Feature code already exists")

        # Create feature
        feature = Feature(
            id=uuid.uuid4(),
            code=req.code,
            name=req.name,
            description=req.description,
            category=req.category,
            active=True
        )
        db.add(feature)
        db.commit()
        db.refresh(feature)

        req_total.labels(operation="create_feature", status="success").inc()
        req_duration.labels(operation="create_feature").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created feature: {feature.id} ({feature.code})")

        return {
            "feature_id": str(feature.id),
            "code": feature.code,
            "name": feature.name,
            "category": feature.category,
            "created_at": feature.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_feature", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        raise HTTPException(status_code=409, detail="Feature code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        logger.error(f"❌ Feature creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/features")
async def list_features(
        active: Optional[bool] = Query(None),
        category: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """List features"""
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if category:
        q = q.filter(Feature.category == category)

    total = q.count()
    features = q.order_by(Feature.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "features": [
            {
                "feature_id": str(f.id),
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "active": f.active,
                "created_at": f.created_at.isoformat()
            }
            for f in features
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.put("/v1/subscriptions/plans/{plan_code}/features/{feature_code}", status_code=201)
async def add_feature_to_plan(
        plan_code: str,
        feature_code: str,
        req: PlanFeatureRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Add a feature to a plan with optional limits"""
    start = datetime.now()
    try:
        req_total.labels(operation="add_plan_feature", status="start").inc()

        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")

        # Check if association exists
        existing = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()

        if existing:
            # Update existing
            existing.enabled = True
            existing.limits = req.limits or {}
            db.commit()
            action = "updated"
        else:
            # Create new
            plan_feature = PlanFeature(
                id=uuid.uuid4(),
                plan_code=plan_code,
                feature_code=feature_code,
                enabled=True,
                limits=req.limits or {}
            )
            db.add(plan_feature)
            db.commit()
            action = "added"

        req_total.labels(operation="add_plan_feature", status="success").inc()
        req_duration.labels(operation="add_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ {action.capitalize()} feature {feature_code} to plan {plan_code}")

        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "enabled": True,
            "limits": req.limits or {},
            "action": action
        }
    except HTTPException:
        req_total.labels(operation="add_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="add_plan_feature", status="error").inc()
        logger.error(f"❌ Add feature to plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans/{plan_code}/features")
async def get_plan_features(
        plan_code: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Get all features for a plan"""
    try:
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        # Get plan features with feature details
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == plan_code, PlanFeature.enabled == True)
            .all()
        )

        return {
            "plan_code": plan_code,
            "plan_name": plan.name,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "category": f.category,
                    "enabled": pf.enabled,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "total": len(features)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get plan features failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/subscriptions/plans/{plan_code}/features/{feature_code}")
async def remove_feature_from_plan(
        plan_code: str,
        feature_code: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Remove a feature from a plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_plan_feature", status="start").inc()

        # Find plan feature association
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()

        if not plan_feature:
            raise HTTPException(status_code=404, detail="Feature not associated with plan")

        # Disable the feature
        plan_feature.enabled = False
        db.commit()

        req_total.labels(operation="remove_plan_feature", status="success").inc()
        req_duration.labels(operation="remove_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Removed feature {feature_code} from plan {plan_code}")

        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "removed": True
        }
    except HTTPException:
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        logger.error(f"❌ Remove feature from plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions", status_code=201)
async def create_subscription(
        req: TenantSubscriptionRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Create a subscription for a tenant"""
    start = datetime.now()
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))
        
        req_total.labels(operation="create_subscription", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        # Check if subscription already exists
        existing = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Subscription already exists for tenant")

        # Calculate subscription periods
        now = datetime.now(timezone.utc)
        period_days = 365 if req.billing_cycle == "yearly" else 30

        # Create subscription
        subscription = TenantSubscription(
            tenant_id=uuid.UUID(req.tenant_id),
            plan_code=req.plan_code,
            payment_method=req.payment_method,
            status="active",
            external_id=f"sub_{req.tenant_id}_{int(now.timestamp())}",
            current_period_start=now,
            current_period_end=now + timedelta(days=period_days)
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)

        req_total.labels(operation="create_subscription", status="success").inc()
        req_duration.labels(operation="create_subscription").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created subscription: {subscription.id} for tenant {req.tenant_id}")

        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_subscription", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        raise HTTPException(status_code=409, detail="Subscription already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        logger.error(f"❌ Subscription creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/subscriptions/{tenant_id}")
async def get_subscription(
        tenant_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Get subscription details for a tenant"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Get plan details
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.code == subscription.plan_code
        ).first()

        # Get plan features
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == subscription.plan_code, PlanFeature.enabled == True)
            .all()
        )

        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "plan_name": plan.name if plan else None,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/renew")
async def renew_subscription(
        tenant_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Renew a subscription - respects original billing cycle"""
    start = datetime.now()
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        req_total.labels(operation="renew_subscription", status="start").inc()

        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Get plan to determine billing cycle
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == subscription.plan_code).first()
        
        # Calculate period based on plan pricing (yearly or monthly)
        # If price_yearly_minor exists, assume yearly; otherwise check current period length
        now = datetime.now(timezone.utc)
        
        if subscription.current_period_start and subscription.current_period_end:
            # Calculate original period length
            period_length = subscription.current_period_end - subscription.current_period_start
            subscription.current_period_start = now
            subscription.current_period_end = now + period_length
        else:
            # Default to yearly if no period exists
            subscription.current_period_start = now
            subscription.current_period_end = now + timedelta(days=365)

        subscription.status = "active"
        subscription.canceled_at = None
        subscription.updated_at = datetime.now(timezone.utc)
        db.commit()

        req_total.labels(operation="renew_subscription", status="success").inc()
        req_duration.labels(operation="renew_subscription").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Renewed subscription for tenant {tenant_id}")

        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "new_period_end": subscription.current_period_end.isoformat(),
            "renewed": True
        }
    except HTTPException:
        req_total.labels(operation="renew_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="renew_subscription", status="error").inc()
        logger.error(f"❌ Renew subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/cancel")
async def cancel_subscription(
        tenant_id: str,
        cancel_at_period_end: bool = Query(True),
        cancellation_reason: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Cancel a subscription with optional immediate cancellation"""
    start = datetime.now()
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        req_total.labels(operation="cancel_subscription", status="start").inc()

        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        now = datetime.now(timezone.utc)
        subscription.canceled_at = now
        subscription.cancellation_reason = cancellation_reason
        
        if cancel_at_period_end:
            subscription.status = "canceled_pending"
        else:
            # Immediate cancellation - refund logic should be here
            subscription.status = "canceled"
            subscription.current_period_end = now

        subscription.updated_at = now
        db.commit()

        req_total.labels(operation="cancel_subscription", status="success").inc()
        req_duration.labels(operation="cancel_subscription").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Canceled subscription for tenant {tenant_id}")

        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "canceled_at": subscription.canceled_at.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "canceled": True
        }
    except HTTPException:
        req_total.labels(operation="cancel_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="cancel_subscription", status="error").inc()
        logger.error(f"❌ Cancel subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/subscriptions/subscriptions/{tenant_id}/plan", status_code=200)
async def change_subscription_plan(
        tenant_id: str,
        new_plan_code: str = Query(...),
        prorate: bool = Query(False),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Change tenant's subscription plan (upgrade/downgrade)"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        # Verify subscription exists
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Verify new plan exists
        new_plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.code == new_plan_code,
            SubscriptionPlan.active == True
        ).first()
        if not new_plan:
            raise HTTPException(status_code=404, detail="New plan not found")
        
        # Store old plan for response
        old_plan_code = subscription.plan_code
        
        # Update plan
        subscription.plan_code = new_plan_code
        subscription.updated_at = datetime.now(timezone.utc)
        
        # If prorating (for upgrades), adjust period end
        if prorate and new_plan.price_yearly_minor:
            # Add logic to adjust billing period based on price difference
            # For now, just update the plan
            pass
        
        db.commit()
        db.refresh(subscription)
        
        logger.info(f"✅ Changed plan: {tenant_id} from {old_plan_code} to {new_plan_code}")
        
        return {
            "tenant_id": tenant_id,
            "old_plan": old_plan_code,
            "new_plan": subscription.plan_code,
            "prorated": prorate,
            "changed_at": subscription.updated_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Change plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/reactivate")
async def reactivate_subscription(
        tenant_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("subscriptions.tenant.manage"))
):
    """Reactivate a canceled subscription"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        if subscription.status not in ["canceled", "canceled_pending", "canceled"]:
            raise HTTPException(status_code=400, detail="Subscription is not canceled")
        
        now = datetime.now(timezone.utc)
        
        # Reactivate subscription
        subscription.status = "active"
        subscription.canceled_at = None
        subscription.cancellation_reason = None
        
        # If period has ended, start new period
        if subscription.current_period_end and subscription.current_period_end < now:
            subscription.current_period_start = now
            # Default to yearly renewal
            subscription.current_period_end = now + timedelta(days=365)
        
        subscription.updated_at = now
        db.commit()
        
        logger.info(f"✅ Reactivated subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "reactivated_at": subscription.updated_at.isoformat(),
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Reactivate subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")