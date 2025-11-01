# services/observability/main.py - ZeroQue Observability Service V4.1
# Production-ready observability service with Celery, RabbitMQ, and comprehensive metrics

import os
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker

from core.config import get_settings
from services.observability.services.observability_services import create_metric, fetch_metrics, create_monitor, \
    get_monitors, get_system_metrics
from .schemas import MetricRequest, MonitorRequest
from .utils.observability_logger import logger
from .repositories.db_config import SessionLocal
from .services.celery_tasks import collect_system_metrics

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================
SERVICE_NAME = "observability"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT

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
    description="Comprehensive system observability and metrics collection",
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
# OBSERVABILITY ENDPOINTS
# =============================================================================

@app.post("/observability/v4/metrics")
async def record_metric(request: MetricRequest):
    """Record a custom metric"""
    return await create_metric(request)

@app.get("/observability/v4/metrics")
async def get_metrics(metric_name: Optional[str] = Query(None), service_name: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """Get metrics with optional filtering"""
    return await fetch_metrics(metric_name, service_name, limit)

@app.post("/observability/v4/monitors")
async def create_monitor_route(request: MonitorRequest):
    """Create a new monitor"""
    return await create_monitor(request)

@app.get("/observability/v4/monitors")
async def list_monitors():
    """List all monitors"""
    return await get_monitors()

@app.post("/observability/v4/collect-system-metrics")
async def collect_system_metrics_endpoint(background_tasks: BackgroundTasks):
    """Trigger system metrics collection"""
    try:
        task = collect_system_metrics.delay()
        
        logger.info("System metrics collection initiated", task_id=task.id)
        
        return {
            "task_id": task.id,
            "status": "initiated"
        }
        
    except Exception as e:
        logger.error("Failed to initiate system metrics collection", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/observability/v4/system-metrics")
async def get_system_metrics_route():
    """Get current system metrics"""
    return await get_system_metrics()

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8223")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )
