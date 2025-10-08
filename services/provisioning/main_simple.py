#!/usr/bin/env python3
"""
Simple Provisioning Service V2 - No Prometheus Metrics
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
SERVICE_NAME = "provisioning"
PORT = int(os.getenv("PORT", "8081"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateTenantPayload(BaseModel):
    tenant_name: str
    tenant_type: str = "standard"
    contact_email: str
    metadata: Optional[Dict[str, Any]] = None

class CreateTenantResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    tenant_type: str
    contact_email: str
    created_at: datetime

class CreateUserPayload(BaseModel):
    tenant_id: str
    email: str
    name: Optional[str] = None
    user_metadata: Optional[Dict[str, Any]] = None

class CreateUserResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    name: Optional[str] = None
    created_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Provisioning Service V2 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Provisioning Service V2")

app = FastAPI(
    title="Provisioning Service V2",
    description="Tenant and user provisioning service",
    version="2.0.0",
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

@app.get("/provisioning/v2/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "provisioning",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/provisioning/v2/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "provisioning",
        "database": "mock"
    }

@app.post("/provisioning/v2/tenants", response_model=CreateTenantResponse)
async def create_tenant(payload: CreateTenantPayload):
    """Create a new tenant"""
    try:
        # Mock tenant creation
        tenant_id = f"tenant_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created tenant {tenant_id} with name {payload.tenant_name}")
        
        return CreateTenantResponse(
            tenant_id=tenant_id,
            tenant_name=payload.tenant_name,
            tenant_type=payload.tenant_type,
            contact_email=payload.contact_email,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create tenant: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/provisioning/v2/users", response_model=CreateUserResponse)
async def create_user(payload: CreateUserPayload):
    """Create a new user"""
    try:
        # Mock user creation
        user_id = f"user_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created user {user_id} for tenant {payload.tenant_id}")
        
        return CreateUserResponse(
            user_id=user_id,
            tenant_id=payload.tenant_id,
            email=payload.email,
            name=payload.name,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/provisioning/v2/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "integrations": {
            "cv-connector": {"connected": True, "events_published": ["USER_CREATED", "TENANT_CREATED"]},
            "identity": {"connected": True, "events_published": ["USER_CREATED"]},
            "entry": {"connected": True, "events_published": ["USER_CREATED"]}
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
