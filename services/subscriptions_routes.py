# ==================================================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ==================================================================================
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query, Request

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


from Models import Tenant, SubscriptionPlan, Feature, PlanFeature, TenantSubscription
from Schemas import UserContext, SubscriptionPlanRequest, FeatureRequest, PlanFeatureRequest, TenantSubscriptionRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger
from utils.metrics import req_total, req_duration

app = APIRouter()

# Event Grid webhook: call internal endpoint to auto-provision base subscription
@app.post("/v1/subscriptions/subscriptions/autoprovision-hook")
async def subscriptions_autoprovision_hook(
        request: Request,
        db: Session = Depends(get_db),
):
    from fastapi import status
    import os
    import json as _json
    import requests as _req

    # Optional shared secret validation
    expected_secret = os.getenv("EVENT_GRID_WEBHOOK_SECRET")
    received_secret = request.query_params.get("secret") or request.headers.get("x-eg-secret")
    aeg_event_type = request.headers.get("aeg-event-type")

    # Parse body once
    body = await request.body()
    try:
        events = _json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
    except Exception:
        events = []

    # Allow validation handshake without secret
    if expected_secret and received_secret != expected_secret and aeg_event_type != "SubscriptionValidation":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    # Validation handshake (EventGrid schema)
    if aeg_event_type == "SubscriptionValidation" and events:
        validation_code = events[0].get("data", {}).get("validationCode")
        if not validation_code:
            raise HTTPException(status_code=400, detail="Missing validation code")
        return {"validationResponse": validation_code}

    # Notifications
    created_any = False
    base_url = os.getenv("INTERNAL_SUBSCRIPTIONS_BASE_URL", "http://localhost:8000")
    plan_code = os.getenv("AUTOPROVISION_DEFAULT_PLAN_CODE", "free")
    billing_cycle = os.getenv("AUTOPROVISION_BILLING_CYCLE", "yearly")
    auth_header = os.getenv("INTERNAL_SUBSCRIPTIONS_AUTH_HEADER")

    headers = {"Content-Type": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header

    for evt in events or []:
        try:
            event_type = evt.get("eventType") or evt.get("type")
            data = evt.get("data") or {}
            tenant_id = data.get("tenant_id")
            if event_type == "tenant.created" and tenant_id:
                payload = {
                    "tenant_id": tenant_id,
                    "plan_code": plan_code,
                    "payment_method": "internal",
                    "billing_cycle": billing_cycle,
                }
                try:
                    resp = _req.post(f"{base_url}/v1/subscriptions/subscriptions", json=payload, headers=headers, timeout=5)
                    if 200 <= resp.status_code < 300:
                        created_any = True
                        logger.info(f"✅ Auto-provisioned via endpoint for tenant {tenant_id}")
                    elif resp.status_code == 409:
                        created_any = True
                        logger.info(f"ℹ️ Subscription already exists for tenant {tenant_id}; treating as success")
                    else:
                        logger.error(f"❌ Autoprovision endpoint failed: {resp.status_code} {resp.text}")
                except Exception as call_err:
                    logger.error(f"❌ Error calling subscriptions endpoint: {call_err}")
        except Exception as e:
            logger.error(f"Autoprovision handler error: {e}")
            db.rollback()

    return {"processed": True, "created": created_any}

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
        ctx: UserContext = Depends(
            require_permission(
                "subscriptions.tenant.manage",
                None
            )
        )
):
    """Create a subscription for a tenant"""
    start = datetime.now()
    try:
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
        ctx: UserContext = Depends(
            require_permission(
                "subscriptions.tenant.manage",
                None
            )
        )
):
    """Get subscription details for a tenant"""
    try:
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
        ctx: UserContext = Depends(
            require_permission(
                "subscriptions.tenant.manage",
                None
            )
        )
):
    """Renew a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="renew_subscription", status="start").inc()

        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Extend subscription by 1 year
        if subscription.current_period_end:
            subscription.current_period_end = subscription.current_period_end + timedelta(days=365)
        else:
            subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=365)

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
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "subscriptions.tenant.manage",
                None
            )
        )
):
    """Cancel a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="cancel_subscription", status="start").inc()

        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        now = datetime.now(timezone.utc)
        subscription.canceled_at = now

        if cancel_at_period_end:
            subscription.status = "canceling"  # Will be canceled at period end
        else:
            subscription.status = "canceled"

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