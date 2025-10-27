# services/subscriptions/main.py - ZeroQue Subscriptions Service v4.1 (Production-Ready)
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
import pybreaker

from .utils.subsciptions_logger import logger
from .models import PlanFeature, SubscriptionPlan, TenantSubscription, Feature
from .schemas import CreatePlanRequest, CreateSubscriptionRequest
from .utils.user_auth import get_user_context, check_permission
from .repositories.db_config import SessionLocal, set_rls_context
from core.config import get_settings
from .core.redis_config import redis_client
from .repositories.database_ops import audit_log

# Config
DATABASE_URL = get_settings().DATABASE_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
REDIS_URL = get_settings().REDIS_URL
SERVICE_NAME = "subscriptions"
SERVICE_VERSION = "4.1.0"
RATE_LIMIT_REQUESTS_PER_MINUTE = 60

# Circuit Breaker
circuit_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)

# =============================================================================
# APP INITIALIZATION
# =============================================================================

# App Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Subscriptions Service v4.1")
    try:
        redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
    yield
    logger.info("Shutting down Subscriptions Service v4.1")

app = FastAPI(
    title="ZeroQue Subscriptions Service",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# =============================================================================
# FEATURE AND PLAN MANAGEMENT ENDPOINTS
# =============================================================================

@app.post("/subscriptions/v2/features")
async def create_feature(
    feature_data: Dict = Body(...),
    user_context: Dict = Depends(get_user_context)
):
    """Create a new feature"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
            feature = Feature(
                code=feature_data["code"],
                name=feature_data["name"],
                description=feature_data.get("description"),
                category=feature_data.get("category"),
                active=True
            )
            db.add(feature)
            db.commit()
            db.refresh(feature)
            
            # Audit disabled for now - schema compatibility issue
            # audit_log(db, user_context.get("tenant_id"), user_context.get("user_id"), "CREATE", "feature", str(feature.id), feature_data)
            
            return {
                "feature_id": str(feature.id),
                "code": feature.code,
                "name": feature.name,
                "created": True
            }
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Feature code already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/subscriptions/v2/plans")
async def create_plan(
    req: CreatePlanRequest,
    user_context: Dict = Depends(get_user_context)
):
    """Create a new subscription plan"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
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
            
            # audit_log temporarily disabled due to schema issues
            # audit_log(db, user_context.get("tenant_id"), user_context.get("user_id"), "CREATE", "plan", str(plan.id), req.dict())
            
            return {
                "plan_id": str(plan.id),
                "code": plan.code,
                "name": plan.name,
                "created": True
            }
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Plan code already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/subscriptions/v2/plans/{plan_code}/features/{feature_code}")
async def add_feature_to_plan(
    plan_code: str,
    feature_code: str,
    limits: Optional[Dict] = Body(None),
    user_context: Dict = Depends(get_user_context)
):
    """Add a feature to a plan with optional limits"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
            # Check if plan and feature exist
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")
            
            feature = db.query(Feature).filter(Feature.code == feature_code).first()
            if not feature:
                raise HTTPException(status_code=404, detail="Feature not found")
            
            # Check if association already exists
            existing = db.query(PlanFeature).filter(
                PlanFeature.plan_code == plan_code,
                PlanFeature.feature_code == feature_code
            ).first()
            
            if existing:
                # Update existing association
                existing.enabled = True
                existing.limits = limits or {}
                db.commit()
                action = "UPDATE"
            else:
                # Create new association
                plan_feature = PlanFeature(
                    plan_code=plan_code,
                    feature_code=feature_code,
                    enabled=True,
                    limits=limits or {}
                )
                db.add(plan_feature)
                db.commit()
                action = "CREATE"
            
            audit_log(db, user_context.get("tenant_id"), user_context.get("user_id"), action, "plan_feature", f"{plan_code}:{feature_code}", {"limits": limits})
            
            return {
                "plan_code": plan_code,
                "feature_code": feature_code,
                "limits": limits,
                "action": action.lower()
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/subscriptions/v2/plans/{plan_code}/features/{feature_code}")
async def remove_feature_from_plan(
    plan_code: str,
    feature_code: str,
    user_context: Dict = Depends(get_user_context)
):
    """Remove a feature from a plan"""
    if not check_permission("subscriptions.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
            # Find and disable the association
            plan_feature = db.query(PlanFeature).filter(
                PlanFeature.plan_code == plan_code,
                PlanFeature.feature_code == feature_code
            ).first()
            
            if not plan_feature:
                raise HTTPException(status_code=404, detail="Feature not associated with plan")
            
            plan_feature.enabled = False
            db.commit()
            
            audit_log(db, user_context.get("tenant_id"), user_context.get("user_id"), "DELETE", "plan_feature", f"{plan_code}:{feature_code}", {})
            
            return {"removed": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# SUBSCRIPTION LIFECYCLE MANAGEMENT
# =============================================================================

@app.post("/subscriptions/v2/subscriptions/{tenant_id}/renew")
async def renew_subscription(
    tenant_id: str,
    payment_method: str = Body(...),
    user_context: Dict = Depends(get_user_context)
):
    """Renew a subscription"""
    if not check_permission("subscriptions.renew", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
            subscription = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()
            if not subscription:
                raise HTTPException(status_code=404, detail="Subscription not found")
            
            # Update subscription period
            subscription.current_period_end = subscription.current_period_end + timedelta(days=365)  # 1 year renewal
            subscription.status = "active"
            subscription.updated_at = datetime.now(timezone.utc)
            
            db.commit()
            
            audit_log(db, tenant_id, user_context.get("user_id"), "RENEW", "subscription", str(subscription.id), {"payment_method": payment_method})
            
            return {
                "subscription_id": str(subscription.id),
                "new_period_end": subscription.current_period_end.isoformat(),
                "renewed": True
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/subscriptions/v2/subscriptions/{tenant_id}/cancel")
async def cancel_subscription(
    tenant_id: str,
    cancel_at_period_end: bool = Body(True),
    user_context: Dict = Depends(get_user_context)
):
    """Cancel a subscription"""
    if not check_permission("subscriptions.cancel", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
            subscription = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()
            if not subscription:
                raise HTTPException(status_code=404, detail="Subscription not found")
            
            if cancel_at_period_end:
                subscription.canceled_at = datetime.now(timezone.utc)
                subscription.status = "canceling"  # Will be canceled at period end
            else:
                subscription.status = "canceled"
                subscription.canceled_at = datetime.now(timezone.utc)
            
            db.commit()
            
            audit_log(db, tenant_id, user_context.get("user_id"), "CANCEL", "subscription", str(subscription.id), {"cancel_at_period_end": cancel_at_period_end})
            
            return {
                "subscription_id": str(subscription.id),
                "status": subscription.status,
                "canceled": True
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/subscriptions/v2/subscriptions/process-renewals")
async def process_subscription_renewals(user_context: Dict = Depends(get_user_context)):
    """Process all subscriptions that need renewal (admin only)"""
    if not check_permission("subscriptions.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        with SessionLocal() as db:
            # Find subscriptions expiring in next 7 days
            cutoff_date = datetime.now(timezone.utc) + timedelta(days=7)
            
            expiring_subscriptions = db.query(TenantSubscription).filter(
                TenantSubscription.current_period_end <= cutoff_date,
                TenantSubscription.status == "active",
                TenantSubscription.canceled_at.is_(None)
            ).all()
            
            renewed_count = 0
            for subscription in expiring_subscriptions:
                try:
                    # Auto-renew subscription
                    subscription.current_period_end = subscription.current_period_end + timedelta(days=365)
                    subscription.updated_at = datetime.now(timezone.utc)
                    
                    # Create billing event (integration with billing service)
                    # This would typically call the billing service to process payment
                    
                    renewed_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to renew subscription {subscription.id}: {e}")
            
            db.commit()
            
            return {
                "processed": len(expiring_subscriptions),
                "renewed": renewed_count,
                "message": f"Processed {len(expiring_subscriptions)} subscriptions, renewed {renewed_count}"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# HEALTH AND METRICS ENDPOINTS
# =============================================================================

# Health
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

# Endpoints
@app.get("/subscriptions/v2/plans")
def list_plans(active: Optional[bool] = Query(None)):
    with SessionLocal() as db:
        query = db.query(SubscriptionPlan)
        if active is not None:
            query = query.filter(SubscriptionPlan.active == active)
        plans = query.all()
        return [{"code": p.code, "name": p.name, "price_yearly_minor": p.price_yearly_minor} for p in plans]

@app.get("/subscriptions/v2/plans/{plan_code}/features")
def list_plan_features(plan_code: str):
    with SessionLocal() as db:
        features = db.query(PlanFeature, Feature).join(Feature).filter(PlanFeature.plan_code == plan_code).all()
        return [{"feature_code": pf.feature_code, "limits": pf.limits or {}} for pf, f in features]

@app.post("/subscriptions/v2/subscriptions")
async def create_subscription(
    req: CreateSubscriptionRequest,
    user_context: Dict = Depends(get_user_context)
):
    """Create a new subscription for a tenant"""
    try:
        if not check_permission(user_context, "subscriptions.create"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            set_rls_context(db, user_context.get("tenant_id", req.tenant_id))
            
            # Check if plan exists
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.plan_code).first()
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")
            
            # Create subscription
            subscription = TenantSubscription(
                tenant_id=req.tenant_id,
                plan_code=req.plan_code,
                payment_method="stripe",
                status="active",
                current_period_start=datetime.now(),
                current_period_end=datetime.now() + timedelta(days=365 if req.billing_cycle == "yearly" else 30)
            )
            db.add(subscription)
            db.commit()
            db.refresh(subscription)
            
            return {
                "subscription_id": str(subscription.id),
                "tenant_id": str(subscription.tenant_id),
                "plan_code": subscription.plan_code,
                "status": subscription.status,
                "created": True
            }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subscriptions/v2/subscriptions/{tenant_id}")
def get_subscription(tenant_id: str):
    try:
        with SessionLocal() as db:
            subscription = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()
            if not subscription:
                raise HTTPException(status_code=404, detail="Subscription not found")
            
            return {
                "subscription_id": str(subscription.id),
                "tenant_id": subscription.tenant_id,
                "plan_code": subscription.plan_code,
                "status": subscription.status,
                "payment_method": subscription.payment_method,
                "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
                "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8212)