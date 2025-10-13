# services/entry/main.py - ZeroQue Entry Service V4.1
# Production-ready entry service with Celery, RabbitMQ, and comprehensive metrics

import os
import uuid
import time
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Query, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError
from celery import Celery
import structlog
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import pybreaker

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "entry"
SERVICE_VERSION = "4.1.0"

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Celery setup
celery_app = Celery(
    SERVICE_NAME,
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=[f'{SERVICE_NAME}.tasks']
)

# Load Celery configuration
try:
    celery_app.config_from_object('celeryconfig')
except ImportError:
    pass

# Prometheus metrics
entry_codes_issued = Counter('entry_codes_issued_total', 'Total entry codes issued', ['tenant_id', 'provider'])
entry_codes_validated = Counter('entry_codes_validated_total', 'Total entry codes validated', ['tenant_id', 'status'])
entry_code_duration = Histogram('entry_code_duration_seconds', 'Entry code operation duration', ['operation'])
active_codes = Gauge('active_entry_codes_total', 'Total active entry codes', ['tenant_id'])

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# Define missing metrics and helper used in Celery tasks
entry_operations_total = Counter('entry_operations_total', 'Entry operations processed', ['operation', 'status'])

def set_rls_context(db, tenant_id: str):
    try:
        db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

# =============================================================================
# DATABASE MODELS
# =============================================================================

class EntryCode(Base):
    __tablename__ = "entry_codes_new"
    
    code_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    code = Column(String(100), unique=True, nullable=False)
    provider = Column(String(50), default="internal")
    status = Column(String(50), default="active")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class IssueCodeRequest(BaseModel):
    tenant_id: str
    user_id: str
    ttl_minutes: int = 60
    provider: str = "internal"

class ValidateCodeRequest(BaseModel):
    code: str
    provider: str = "internal"

class EntryCodeResponse(BaseModel):
    code: str
    code_id: str
    tenant_id: str
    user_id: str
    expires_at: datetime
    ttl_minutes: int

class ValidationResponse(BaseModel):
    valid: bool
    reason: Optional[str] = None
    code: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_codes(self):
    """Clean up expired entry codes"""
    try:
        with SessionLocal() as db:
            # Clean up expired codes from database
            expired_codes = db.query(EntryCode).filter(
                EntryCode.expires_at < datetime.now(timezone.utc),
                EntryCode.status == "active"
            ).all()
            
            for code in expired_codes:
                code.status = "expired"
                
                # Remove from Redis
                redis_key = f"entry:{code.code}"
                redis_client.delete(redis_key)
            
            db.commit()
            
        logger.info("Cleaned up expired codes", count=len(expired_codes))
        return {"cleaned_count": len(expired_codes)}
        
    except Exception as e:
        logger.error("Failed to cleanup expired codes", error=str(e))
        
        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {"error": str(e)}

# =============================================================================
# APPLICATION SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME}", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    # Initialize database tables
    try:
        Base.metadata.create_all(bind=engine)
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

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
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
async def issue_code(request: IssueCodeRequest):
    """Issue an entry code"""
    start_time = time.time()
    
    try:
        code = f"ENTRY{uuid.uuid4().hex[:8].upper()}"
        code_id = f"code_{uuid.uuid4().hex[:12]}"
        
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=request.ttl_minutes)
        
        # Store in Redis
        redis_key = f"entry:{code}"
        redis_value = f"{request.tenant_id}:{request.user_id}"
        redis_client.setex(redis_key, request.ttl_minutes * 60, redis_value)
        
        # Store in DB
        with SessionLocal() as db:
            entry_code = EntryCode(
                code_id=code_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                code=code,
                provider=request.provider,
                status="active",
                expires_at=expires_at
            )
            db.add(entry_code)
            db.commit()
        
        # Update metrics
        entry_codes_issued.labels(tenant_id=request.tenant_id, provider=request.provider).inc()
        entry_code_duration.labels(operation="issue").observe(time.time() - start_time)
        active_codes.labels(tenant_id=request.tenant_id).inc()
        
        logger.info("Entry code issued", 
                   code=code, tenant_id=request.tenant_id, user_id=request.user_id)
        
        return EntryCodeResponse(
            code=code,
            code_id=code_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            expires_at=expires_at,
            ttl_minutes=request.ttl_minutes
        )
    
    except Exception as e:
        logger.error("Issue code failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entry/v4/validate-code", response_model=ValidationResponse)
async def validate_code(request: ValidateCodeRequest):
    """Validate an entry code"""
    start_time = time.time()
    
    try:
        redis_key = f"entry:{request.code}"
        value = redis_client.get(redis_key)
        
        if not value:
            # Update metrics
            entry_codes_validated.labels(tenant_id="unknown", status="invalid").inc()
            entry_code_duration.labels(operation="validate").observe(time.time() - start_time)
            
            return ValidationResponse(
                valid=False,
                reason="Code not found or expired",
                code=request.code
            )
        
        # Parse tenant_id and user_id from Redis value
        tenant_id, user_id = value.split(":", 1)
        
        # Mark as consumed
        redis_client.delete(redis_key)
        
        # Update DB
        with SessionLocal() as db:
            db.execute(
                text("UPDATE entry_codes_new SET status = 'consumed' WHERE code = :code"),
                {"code": request.code}
            )
            db.commit()
        
        # Update metrics
        entry_codes_validated.labels(tenant_id=tenant_id, status="valid").inc()
        entry_code_duration.labels(operation="validate").observe(time.time() - start_time)
        active_codes.labels(tenant_id=tenant_id).dec()
        
        logger.info("Entry code validated", 
                   code=request.code, tenant_id=tenant_id, user_id=user_id)
        
        return ValidationResponse(
            valid=True,
            code=request.code,
            tenant_id=tenant_id,
            user_id=user_id
        )
    
    except Exception as e:
        logger.error("Validate code failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/entry/v4/codes")
async def list_codes(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """List entry codes with optional filtering"""
    try:
        with SessionLocal() as db:
            query = db.query(EntryCode)
            
            if tenant_id:
                query = query.filter(EntryCode.tenant_id == tenant_id)
            if status:
                query = query.filter(EntryCode.status == status)
                
            codes = query.order_by(EntryCode.created_at.desc()).limit(limit).all()
            
            return [
                {
                    "code_id": code.code_id,
                    "tenant_id": code.tenant_id,
                    "user_id": code.user_id,
                    "code": code.code,
                    "provider": code.provider,
                    "status": code.status,
                    "expires_at": code.expires_at,
                    "created_at": code.created_at
                }
                for code in codes
            ]
            
    except Exception as e:
        logger.error("Failed to list codes", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/entry/v4/status/{code}")
async def get_code_status(code: str):
    """Get entry code status"""
    try:
        redis_key = f"entry:{code}"
        exists = redis_client.exists(redis_key)
        
        if exists:
            value = redis_client.get(redis_key)
            ttl = redis_client.ttl(redis_key)
            tenant_id, user_id = value.split(":")
            
            return {
                "exists": True,
                "code": code,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "ttl_seconds": ttl,
                "status": "active"
            }
        else:
            # Check DB
            with SessionLocal() as db:
                result = db.execute(
                    text("SELECT tenant_id, user_id, status FROM entry_codes_new WHERE code = :code"),
                    {"code": code}
                ).first()
                
                if result:
                    return {
                        "exists": True,
                        "code": code,
                        "tenant_id": result[0],
                        "user_id": result[1],
                        "status": result[2]
                    }
        
        return {"exists": False, "code": code}
    
    except Exception as e:
        logger.error("Status check failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_entry_codes(self):
    """Clean up expired entry codes"""
    try:
        with SessionLocal() as db:
            # Clean up expired codes from database
            result = db.execute(text("""
                DELETE FROM entry_codes_new 
                WHERE expires_at < NOW() AND status = 'active'
            """))
            
            db.commit()
            
            # Clean up expired codes from Redis
            expired_keys = []
            for key in redis_client.scan_iter(match="entry_code:*"):
                ttl = redis_client.ttl(key)
                if ttl == -1:  # Key exists but no TTL set
                    redis_client.delete(key)
                    expired_keys.append(key)
                elif ttl == -2:  # Key doesn't exist
                    expired_keys.append(key)
            
            logger.info(f"Cleaned up {result.rowcount} expired entry codes from DB and {len(expired_keys)} from Redis")
            
    except Exception as e:
        logger.error(f"Failed to cleanup expired entry codes: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3)
def process_entry_granted(self, tenant_id: str, user_id: str, code: str):
    """Process entry granted event"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process entry granted logic here
            logger.info(f"Processing entry granted for tenant {tenant_id}, user {user_id}, code {code}")
            
            # Update metrics
            entry_operations_total.labels(operation="granted", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process entry granted: {e}")
        entry_operations_total.labels(operation="granted", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_entry_denied(self, tenant_id: str, user_id: str, code: str, reason: str):
    """Process entry denied event"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process entry denied logic here
            logger.info(f"Processing entry denied for tenant {tenant_id}, user {user_id}, code {code}, reason {reason}")
            
            # Update metrics
            entry_operations_total.labels(operation="denied", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process entry denied: {e}")
        entry_operations_total.labels(operation="denied", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

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