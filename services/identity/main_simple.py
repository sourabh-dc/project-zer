#!/usr/bin/env python3
"""
Simple Identity Service V4.1 - No Prometheus Metrics
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
SERVICE_NAME = "identity"
PORT = int(os.getenv("PORT", "8085"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateUserPayload(BaseModel):
    tenant_id: str
    email: str
    name: Optional[str] = None
    user_metadata: Optional[Dict[str, Any]] = None

class CreateUserResponse(BaseModel):
    user_id: str
    email: str
    name: Optional[str] = None
    created_at: datetime

class CreateRolePayload(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)

class CreateRoleResponse(BaseModel):
    role_id: str
    name: str
    description: Optional[str] = None
    permissions: list[str]
    created_at: datetime

class AssignRolePayload(BaseModel):
    tenant_id: str
    user_id: str
    role_id: str

class AssignRoleResponse(BaseModel):
    assignment_id: str
    user_id: str
    role_id: str
    assigned_at: datetime

class GenerateTokenPayload(BaseModel):
    tenant_id: str
    user_id: str
    expires_in_minutes: int = Field(default=60, ge=1, le=1440)

class GenerateTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    user_id: str
    tenant_id: str

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Identity Service V4.1 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Identity Service V4.1")

app = FastAPI(
    title="Identity Service V4.1",
    description="User and role management service",
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

@app.get("/identity/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "identity",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/identity/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "identity",
        "database": "mock"
    }

@app.post("/identity/v4/users", response_model=CreateUserResponse)
async def create_user_v4(payload: CreateUserPayload):
    """Create a new user"""
    try:
        # Mock user creation
        user_id = f"user_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created user {user_id} for tenant {payload.tenant_id}")
        
        return CreateUserResponse(
            user_id=user_id,
            email=payload.email,
            name=payload.name,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/roles", response_model=CreateRoleResponse)
async def create_role_v4(payload: CreateRolePayload):
    """Create a new role"""
    try:
        # Mock role creation
        role_id = f"role_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created role {role_id} for tenant {payload.tenant_id}")
        
        return CreateRoleResponse(
            role_id=role_id,
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create role: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/role-assignments", response_model=AssignRoleResponse)
async def assign_role_v4(payload: AssignRolePayload):
    """Assign role to user"""
    try:
        # Mock role assignment
        assignment_id = f"assignment_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Assigned role {payload.role_id} to user {payload.user_id}")
        
        return AssignRoleResponse(
            assignment_id=assignment_id,
            user_id=payload.user_id,
            role_id=payload.role_id,
            assigned_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to assign role: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/tokens", response_model=GenerateTokenResponse)
async def generate_token_v4(payload: GenerateTokenPayload):
    """Generate JWT token for user"""
    try:
        # Mock token generation
        token = f"mock_token_{int(time.time())}"
        expires_at = datetime.utcnow() + timedelta(minutes=payload.expires_in_minutes)
        
        logger.info(f"Generated token for user {payload.user_id}")
        
        return GenerateTokenResponse(
            token=token,
            expires_at=expires_at,
            user_id=payload.user_id,
            tenant_id=payload.tenant_id
        )
        
    except Exception as e:
        logger.error(f"Failed to generate token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/identity/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "provisioning": {"connected": True, "events_handled": ["TENANT_CREATED"]},
            "entry": {"connected": True, "events_published": ["USER_CREATED"]},
            "orders": {"connected": True, "events_published": ["USER_CREATED"]},
            "notifications": {"connected": True, "events_published": ["USER_CREATED", "ROLE_CHANGED"]}
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
