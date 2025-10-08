#!/usr/bin/env python3
"""
Simple Subscriptions Service V4.1 - No Prometheus Metrics
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
SERVICE_NAME = "subscriptions"
PORT = int(os.getenv("PORT", "8095"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateSubscriptionPayload(BaseModel):
    tenant_id: str
    plan_id: str
    payment_method_id: Optional[str] = None
    start_date: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

class CreateSubscriptionResponse(BaseModel):
    subscription_id: str
    tenant_id: str
    plan_id: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime

class UpdateSubscriptionPayload(BaseModel):
    subscription_id: str
    plan_id: Optional[str] = None
    payment_method_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class UpdateSubscriptionResponse(BaseModel):
    subscription_id: str
    plan_id: str
    status: str
    updated_at: datetime

class CancelSubscriptionPayload(BaseModel):
    subscription_id: str
    cancel_at_period_end: bool = True
    cancellation_reason: Optional[str] = None

class CancelSubscriptionResponse(BaseModel):
    subscription_id: str
    status: str
    canceled_at: datetime
    cancel_at_period_end: bool

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Subscriptions Service V4.1 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Subscriptions Service V4.1")

app = FastAPI(
    title="Subscriptions Service V4.1",
    description="Subscription management service",
    version="4.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/subscriptions/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "subscriptions",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/subscriptions/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "subscriptions",
        "database": "mock"
    }

@app.post("/subscriptions/v4/subscriptions", response_model=CreateSubscriptionResponse)
async def create_subscription(payload: CreateSubscriptionPayload):
    """Create subscription"""
    try:
        # Mock subscription creation
        subscription_id = f"sub_{int(time.time())}"
        now = datetime.utcnow()
        period_end = now + timedelta(days=30)
        
        logger.info(f"Created subscription {subscription_id} for tenant {payload.tenant_id}")
        
        return CreateSubscriptionResponse(
            subscription_id=subscription_id,
            tenant_id=payload.tenant_id,
            plan_id=payload.plan_id,
            status="active",
            current_period_start=now,
            current_period_end=period_end,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/subscriptions/v4/subscriptions/{subscription_id}", response_model=UpdateSubscriptionResponse)
async def update_subscription(subscription_id: str, payload: UpdateSubscriptionPayload):
    """Update subscription"""
    try:
        # Mock subscription update
        now = datetime.utcnow()
        
        logger.info(f"Updated subscription {subscription_id}")
        
        return UpdateSubscriptionResponse(
            subscription_id=subscription_id,
            plan_id=payload.plan_id or "basic_plan",
            status="active",
            updated_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to update subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/subscriptions/v4/subscriptions/{subscription_id}/cancel", response_model=CancelSubscriptionResponse)
async def cancel_subscription(subscription_id: str, payload: CancelSubscriptionPayload):
    """Cancel subscription"""
    try:
        # Mock subscription cancellation
        now = datetime.utcnow()
        
        logger.info(f"Canceled subscription {subscription_id}")
        
        return CancelSubscriptionResponse(
            subscription_id=subscription_id,
            status="canceled",
            canceled_at=now,
            cancel_at_period_end=payload.cancel_at_period_end
        )
        
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subscriptions/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "payments": {"connected": True, "events_handled": ["PAYMENT_PAID"]},
            "entitlements": {"connected": True, "events_published": ["PLAN_CHANGED"]},
            "billing": {"connected": True, "events_published": ["SUBSCRIPTION_CREATED"]}
        },
        "status": {
            "database_available": False,
            "metrics_enabled": False
        }
    }

# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main_simple:app",
        host="0.0.0.0",
        port=PORT,
        reload=os.getenv("ENVIRONMENT") == "development"
    )
