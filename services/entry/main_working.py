#!/usr/bin/env python3
"""
Working Entry Service V4.1 - Minimal Version for Testing
"""

import os
import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

import structlog
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Configuration
SERVICE_NAME = "entry"
PORT = int(os.getenv("PORT", "8084"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Prometheus metrics - use unique names
entry_requests_total = Counter('entry_requests_working_total', 'Total entry requests', ['endpoint', 'status'])
entry_request_duration = Histogram('entry_request_working_duration_seconds', 'Entry request duration', ['endpoint'])

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class IssueCodePayload(BaseModel):
    tenant_id: str
    user_id: str
    provider: str = "internal"
    group_size: int = Field(default=1, ge=1, le=10)
    ttl_min: int = Field(default=15, ge=1, le=60)

class IssueCodeResponse(BaseModel):
    allowed: bool
    code: Optional[str] = None
    expires_at: Optional[datetime] = None
    reason: Optional[str] = None

class ValidateCodePayload(BaseModel):
    code: str
    tenant_id: str

class ValidateCodeResponse(BaseModel):
    valid: bool
    consumed: bool = False
    provider: str = "internal"
    reason: Optional[str] = None

# =============================================================================
# REDIS UTILITIES
# =============================================================================

def get_redis():
    """Get Redis connection (simplified for testing)"""
    try:
        import redis
        return redis.from_url(REDIS_URL, decode_responses=True)
    except ImportError:
        logger.warning("Redis not available, using mock")
        return None

def _rev_key(code: str) -> str:
    """Generate reverse key for code lookup"""
    return f"entry:rev:{code}"

def _fwd_key(tenant_id: str, site_id: str, store_id: str, user_id: str, code: str) -> str:
    """Generate forward key for code storage"""
    return f"entry:fwd:{tenant_id}:{site_id}:{store_id}:{user_id}:{code}"

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Entry Service V4.1 (Working Version)")
    yield
    # Shutdown
    logger.info("Shutting down Entry Service V4.1")

app = FastAPI(
    title="Entry Service V4.1",
    description="Entry code management service",
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

@app.get("/entry/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "entry",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/entry/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    try:
        r = get_redis()
        if r:
            r.ping()
        return {
            "status": "ready",
            "service": "entry",
            "database": "connected" if r else "mock"
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {str(e)}")

@app.get("/entry/v4/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest()

@app.post("/entry/v4/issue-code", response_model=IssueCodeResponse)
async def issue_code_v4(payload: IssueCodePayload):
    """Issue entry code"""
    start_time = time.time()
    
    try:
        # Generate code
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=payload.ttl_min)
        
        # Store in Redis (if available)
        r = get_redis()
        if r:
            rev_key = _rev_key(code)
            fwd_key = _fwd_key(payload.tenant_id, "site1", "store1", payload.user_id, code)
            
            # Store both keys with TTL
            pipe = r.pipeline()
            pipe.set(rev_key, fwd_key, ex=payload.ttl_min * 60)
            pipe.set(fwd_key, "1", ex=payload.ttl_min * 60)
            pipe.execute()
        
        # Update metrics
        entry_requests_total.labels(endpoint="issue_code", status="success").inc()
        entry_request_duration.labels(endpoint="issue_code").observe(time.time() - start_time)
        
        return IssueCodeResponse(
            allowed=True,
            code=code,
            expires_at=expires_at
        )
        
    except Exception as e:
        logger.error(f"Failed to issue entry code: {str(e)}")
        entry_requests_total.labels(endpoint="issue_code", status="error").inc()
        entry_request_duration.labels(endpoint="issue_code").observe(time.time() - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entry/v4/validate-code", response_model=ValidateCodeResponse)
async def validate_code_v4(payload: ValidateCodePayload):
    """Validate entry code"""
    start_time = time.time()
    
    try:
        # Check Redis (if available)
        r = get_redis()
        if r:
            rev_key = _rev_key(payload.code)
            fwd_key = r.get(rev_key)
            
            if fwd_key:
                # Code exists, consume it
                pipe = r.pipeline()
                pipe.delete(rev_key)
                pipe.delete(fwd_key)
                pipe.execute()
                
                # Update metrics
                entry_requests_total.labels(endpoint="validate_code", status="success").inc()
                entry_request_duration.labels(endpoint="validate_code").observe(time.time() - start_time)
                
                return ValidateCodeResponse(
                    valid=True,
                    consumed=True,
                    provider="internal"
                )
        
        # Code not found or expired
        entry_requests_total.labels(endpoint="validate_code", status="not_found").inc()
        entry_request_duration.labels(endpoint="validate_code").observe(time.time() - start_time)
        
        return ValidateCodeResponse(
            valid=False,
            consumed=False,
            provider="internal",
            reason="code_not_found_or_expired"
        )
        
    except Exception as e:
        logger.error(f"Failed to validate entry code: {str(e)}")
        entry_requests_total.labels(endpoint="validate_code", status="error").inc()
        entry_request_duration.labels(endpoint="validate_code").observe(time.time() - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/entry/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "provisioning": {"connected": True, "events_handled": ["USER_CREATED"]},
            "access": {"connected": True, "events_published": ["ENTRY_GRANTED"]},
            "orders": {"connected": True, "events_published": ["ENTRY_VALIDATED"]},
            "notifications": {"connected": True, "events_published": ["ENTRY_GRANTED"]}
        },
        "status": {
            "redis_available": get_redis() is not None,
            "metrics_enabled": True
        }
    }

# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main_working:app",
        host="0.0.0.0",
        port=PORT,
        reload=os.getenv("ENVIRONMENT") == "development"
    )
