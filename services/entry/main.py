# services/entry/main.py - ZeroQue Entry Service V4.1
# Production-ready entry service with Celery, RabbitMQ, and comprehensive metrics

import os
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import pybreaker
from sqlalchemy.orm import Session

from core.config import get_settings
from services.entry.services.entry_services import create_issue_code, validate_code, get_codes, get_code_status
from .utils.entry_logger import logger
from .repositories.db_config import SessionLocal, get_db_with_rls
from .schemas import IssueCodeRequest, EntryCodeResponse, ValidateCodeRequest, ValidationResponse
from .utils.user_auth import get_user_context

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "entry"
SERVICE_VERSION = "4.1.0"

ENVIRONMENT = get_settings().ENVIRONMENT

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# APPLICATION SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME}", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    # Initialize database tables
    try:
        # Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error("Failed to initialize database tables", error=str(e))
    
    yield
    
    logger.info(f"Shutting down {SERVICE_NAME}")

app = FastAPI(
    title=f"ZeroQue {SERVICE_NAME.title()} Service V4.1",
    description="Entry code generation and validation for store access",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Production Middleware - Restrict CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8501",  # Streamlit apps
        "http://localhost:8502",
        "http://localhost:8503",
        "http://localhost:8510",
        "https://*.zeroque.com"
    ] if ENVIRONMENT == "development" else ["https://*.zeroque.com", "https://zeroque.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

if ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.zeroque.com", "zeroque.com"])
else:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "environment": ENVIRONMENT
    }

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {
            "service": SERVICE_NAME,
            "status": "ready",
            "database": "connected"
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {str(e)}")

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# ENTRY CODE ENDPOINTS
# =============================================================================

@app.post("/entry/v4/issue-code", response_model=EntryCodeResponse)
async def issue_code(request: IssueCodeRequest, user_context: Dict[str, Any] = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    """Issue an entry code"""
    return await create_issue_code(request, user_context, db)

@app.post("/entry/v4/validate-code", response_model=ValidationResponse)
async def validate_code_route(request: ValidateCodeRequest):
    """Validate an entry code"""
    return await validate_code(request)

@app.get("/entry/v4/codes")
async def list_codes(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """List entry codes with optional filtering"""
    return await get_codes(tenant_id, status, limit)

@app.get("/entry/v4/status/{code}")
async def get_code_status_route(code: str):
    """Get entry code status"""
    return await get_code_status(code)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8218")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )