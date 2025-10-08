#!/usr/bin/env python3
"""
Simple Entitlements Service V4.1 - No Prometheus Metrics
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
from datetime import datetime

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
SERVICE_NAME = "entitlements"
PORT = int(os.getenv("PORT", "8094"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateEntitlementPayload(BaseModel):
    tenant_id: str
    feature_code: str
    limits: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

class CreateEntitlementResponse(BaseModel):
    entitlement_id: str
    tenant_id: str
    feature_code: str
    limits: Dict[str, Any]
    created_at: datetime

class CheckEntitlementPayload(BaseModel):
    tenant_id: str
    feature_code: str
    user_id: Optional[str] = None
    action: str = "access"

class CheckEntitlementResponse(BaseModel):
    allowed: bool
    feature_code: str
    remaining_limit: Optional[int] = None
    reason: Optional[str] = None

class UpdateUsagePayload(BaseModel):
    tenant_id: str
    feature_code: str
    usage_amount: int
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class UpdateUsageResponse(BaseModel):
    success: bool
    new_total_usage: int
    remaining_limit: int
    message: str

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Entitlements Service V4.1 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Entitlements Service V4.1")

app = FastAPI(
    title="Entitlements Service V4.1",
    description="Feature entitlements and usage tracking service",
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

@app.get("/entitlements/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "entitlements",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/entitlements/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "entitlements",
        "database": "mock"
    }

@app.post("/entitlements/v4/entitlements", response_model=CreateEntitlementResponse)
async def create_entitlement(payload: CreateEntitlementPayload):
    """Create entitlement for tenant"""
    try:
        # Mock entitlement creation
        entitlement_id = f"ent_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created entitlement {entitlement_id} for tenant {payload.tenant_id}")
        
        return CreateEntitlementResponse(
            entitlement_id=entitlement_id,
            tenant_id=payload.tenant_id,
            feature_code=payload.feature_code,
            limits=payload.limits,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create entitlement: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entitlements/v4/check", response_model=CheckEntitlementResponse)
async def check_entitlement(payload: CheckEntitlementPayload):
    """Check if tenant/user has entitlement for feature"""
    try:
        # Mock entitlement check
        allowed = True
        remaining_limit = 1000
        
        logger.info(f"Checked entitlement for {payload.feature_code} in tenant {payload.tenant_id}")
        
        return CheckEntitlementResponse(
            allowed=allowed,
            feature_code=payload.feature_code,
            remaining_limit=remaining_limit,
            reason="Entitlement granted"
        )
        
    except Exception as e:
        logger.error(f"Failed to check entitlement: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entitlements/v4/usage", response_model=UpdateUsageResponse)
async def update_usage(payload: UpdateUsagePayload):
    """Update usage for feature"""
    try:
        # Mock usage update
        new_total_usage = 100
        remaining_limit = 900
        
        logger.info(f"Updated usage for {payload.feature_code} in tenant {payload.tenant_id}")
        
        return UpdateUsageResponse(
            success=True,
            new_total_usage=new_total_usage,
            remaining_limit=remaining_limit,
            message="Usage updated successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to update usage: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/entitlements/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "subscriptions": {"connected": True, "events_handled": ["PLAN_CHANGED"]},
            "usage": {"connected": True, "events_handled": ["USAGE_RECORDED"]},
            "pricing": {"connected": True, "events_handled": ["PRICE_RESOLVED"]}
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
