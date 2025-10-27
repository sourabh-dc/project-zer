# services/subscriptions/main.py - ZeroQue Subscriptions Service v4.1 (Production-Ready)
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
import pybreaker
from sqlalchemy.orm import Session

from services.subscriptions.services.subscription_services import create_feature, create_plan, add_feature_to_plan, \
    remove_feature_from_plan, renew_subscription
from .utils.subsciptions_logger import logger
from .models import PlanFeature, SubscriptionPlan, TenantSubscription, Feature
from .schemas import CreatePlanRequest, CreateSubscriptionRequest
from .utils.user_auth import get_user_context, check_permission
from .repositories.db_config import SessionLocal, set_rls_context, get_db
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
async def create_feature_route(feature_data: Dict = Body(...), user_context: Dict = Depends(get_user_context), db: Session=get_db
):
    """Create a new feature"""
    return await create_feature(feature_data, user_context, db)

@app.post("/subscriptions/v2/plans")
async def create_plan_route(req: CreatePlanRequest, user_context: Dict = Depends(get_user_context), db: Session=get_db
):
    """Create a new subscription plan"""
    return await create_plan(req, user_context, db)

@app.put("/subscriptions/v2/plans/{plan_code}/features/{feature_code}")
async def add_feature_to_plan_route(plan_code: str, feature_code: str, limits: Optional[Dict] = Body(None),
    user_context: Dict = Depends(get_user_context), db: Session=get_db):
    """Add a feature to a plan with optional limits"""
    return await add_feature_to_plan(plan_code, feature_code, limits, user_context, db)

@app.delete("/subscriptions/v2/plans/{plan_code}/features/{feature_code}")
async def remove_feature_from_plan_route(plan_code: str, feature_code: str, user_context: Dict = Depends(get_user_context),
                                        db:Session=get_db):
    """Remove a feature from a plan"""
    return remove_feature_from_plan(plan_code, feature_code, user_context, db)

# =============================================================================
# SUBSCRIPTION LIFECYCLE MANAGEMENT
# =============================================================================

@app.post("/subscriptions/v2/subscriptions/{tenant_id}/renew")
async def renew_subscription_route(tenant_id: str, payment_method: str = Body(...), user_context: Dict = Depends(get_user_context),
                             db: Session=get_db):
    """Renew a subscription"""
    return await renew_subscription(tenant_id, payment_method, user_context, db)

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