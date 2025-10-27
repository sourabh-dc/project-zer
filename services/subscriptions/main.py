# services/subscriptions/main.py - ZeroQue Subscriptions Service v4.1 (Production-Ready)
from typing import Optional, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
import pybreaker
from sqlalchemy.orm import Session

from services.subscriptions.services.subscription_services import create_feature, create_plan, add_feature_to_plan, \
    remove_feature_from_plan, renew_subscription, cancel_subscription, process_subscription_renewals, \
    create_subscription, get_subscription_by_tenant, get_plans, list_plan_features
from .utils.subsciptions_logger import logger
from .schemas import CreatePlanRequest, CreateSubscriptionRequest
from .utils.user_auth import get_user_context
from .repositories.db_config import get_db
from core.config import get_settings
from .core.redis_config import redis_client

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
async def cancel_subscription_route(tenant_id: str, cancel_at_period_end: bool = Body(True), user_context: Dict = Depends(get_user_context),
                              db: Session=get_db):
    """Cancel a subscription"""
    return await cancel_subscription(tenant_id, cancel_at_period_end, user_context, db)

@app.post("/subscriptions/v2/subscriptions/process-renewals")
async def process_subscription_renewals_route(user_context: Dict = Depends(get_user_context), db: Session=get_db):
    """Process all subscriptions that need renewal (admin only)"""
    return await process_subscription_renewals(user_context, db)

# =============================================================================
# HEALTH AND METRICS ENDPOINTS
# =============================================================================

# Health
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

# Endpoints
@app.get("/subscriptions/v2/plans")
async def list_plans(active: Optional[bool] = Query(None), db: Session = Depends(get_db)):
    return await get_plans(active, db)


@app.get("/subscriptions/v2/plans/{plan_code}/features")
async def list_plan_features_route(plan_code: str, db: Session = Depends(get_db)):
    return await list_plan_features(plan_code, db)


@app.post("/subscriptions/v2/subscriptions")
async def create_subscription_route(req: CreateSubscriptionRequest, user_context: Dict = Depends(get_user_context),
                                db: Session = get_db):
    """Create a new subscription for a tenant"""
    return await create_subscription(req, user_context, db)

@app.get("/subscriptions/v2/subscriptions/{tenant_id}")
async def get_subscription(tenant_id: str, db: Session = Depends(get_db)):
    return await get_subscription_by_tenant(tenant_id, db)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8212)