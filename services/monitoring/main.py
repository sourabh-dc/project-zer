# services/monitoring/main.py - ZeroQue Monitoring Service V4.1
# Production-ready monitoring service with Celery, RabbitMQ, and comprehensive metrics
import os
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker

from core.config import get_settings
from services.monitoring.services.monitoring_services import check_health, get_service_health_status, get_services, \
    create_alert, get_alerts
from .utils.monitoring_logger import logger
from .schemas import (HealthCheckRequest, AlertRequest)
from .repositories.db_config import SessionLocal

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "monitoring"
SERVICE_VERSION = "4.1.0"
ENVIRONMENT = get_settings().ENVIRONMENT
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

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
    description="Comprehensive service monitoring and health checking",
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
# MONITORING ENDPOINTS
# =============================================================================

@app.post("/monitoring/v4/check-health")
async def check_health_route(request: HealthCheckRequest):
    """Initiate health check for a service"""
    return await check_health(request)

@app.get("/monitoring/v4/services/{service_name}/status")
async def get_service_status(service_name: str):
    """Get current status of a service"""
    return await get_service_health_status(service_name)

@app.get("/monitoring/v4/services")
async def list_services():
    """List all monitored services"""
    return await get_services()

@app.post("/monitoring/v4/alerts")
async def create_alert_route(request: AlertRequest):
    """Create a new alert"""
    return await create_alert(request)

@app.get("/monitoring/v4/alerts")
async def list_alerts(service_name: Optional[str] = Query(None), severity: Optional[str] = Query(None), status: str = Query("active")
):
    """List alerts with optional filtering"""
    return await get_alerts(service_name, severity, status)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8221")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )
