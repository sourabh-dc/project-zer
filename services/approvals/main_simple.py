#!/usr/bin/env python3
"""
Simple Approvals Service V2 - No Prometheus Metrics
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
SERVICE_NAME = "approvals"
PORT = int(os.getenv("PORT", "8088"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateApprovalRequestPayload(BaseModel):
    tenant_id: str
    user_id: str
    amount_minor: int
    currency: str = "USD"
    reason: str
    cost_centre_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class CreateApprovalRequestResponse(BaseModel):
    request_id: str
    tenant_id: str
    user_id: str
    amount_minor: int
    currency: str
    status: str
    created_at: datetime

class ApproveRequestPayload(BaseModel):
    request_id: str
    approver_id: str
    comments: Optional[str] = None

class ApproveRequestResponse(BaseModel):
    request_id: str
    status: str
    approved_by: str
    approved_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Approvals Service V2 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Approvals Service V2")

app = FastAPI(
    title="Approvals Service V2",
    description="Approval workflow management service",
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

@app.get("/approvals/v2/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "approvals",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/approvals/v2/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "approvals",
        "database": "mock"
    }

@app.post("/approvals/v2/requests", response_model=CreateApprovalRequestResponse)
async def create_approval_request(payload: CreateApprovalRequestPayload):
    """Create a new approval request"""
    try:
        # Mock approval request creation
        request_id = f"approval_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created approval request {request_id} for tenant {payload.tenant_id}")
        
        return CreateApprovalRequestResponse(
            request_id=request_id,
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            status="pending",
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create approval request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/approvals/v2/requests/{request_id}/approve", response_model=ApproveRequestResponse)
async def approve_request(request_id: str, payload: ApproveRequestPayload):
    """Approve a request"""
    try:
        # Mock approval
        now = datetime.utcnow()
        
        logger.info(f"Approved request {request_id} by {payload.approver_id}")
        
        return ApproveRequestResponse(
            request_id=request_id,
            status="approved",
            approved_by=payload.approver_id,
            approved_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to approve request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/approvals/v2/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "integrations": {
            "ledger": {"connected": True, "events_published": ["APPROVAL_RESOLVED"]},
            "cv-gateway": {"connected": True, "events_handled": ["BUDGET_CHECK"]}
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
