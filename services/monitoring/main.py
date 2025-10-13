# services/monitoring/main.py - ZeroQue Monitoring Service V4.1
# Production-ready monitoring service with Celery, RabbitMQ, and comprehensive metrics

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

SERVICE_NAME = "monitoring"
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
monitoring_checks_total = Counter('monitoring_checks_total', 'Total monitoring checks', ['service', 'status'])
monitoring_check_duration = Histogram('monitoring_check_duration_seconds', 'Monitoring check duration', ['service'])
service_health_status = Gauge('service_health_status', 'Service health status', ['service'])
active_alerts = Gauge('active_alerts_total', 'Total active alerts', ['severity'])

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# DATABASE MODELS
# =============================================================================

class ServiceHealth(Base):
    __tablename__ = "service_health_new"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    service_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # healthy, unhealthy, degraded
    response_time_ms = Column(Integer, nullable=True)
    last_check = Column(DateTime(timezone=True), server_default=func.now())
    error_message = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Alert(Base):
    __tablename__ = "alerts_new"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    service_name = Column(String, nullable=False)
    alert_type = Column(String, nullable=False)  # health_check, performance, error_rate
    severity = Column(String, nullable=False)  # critical, warning, info
    message = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="active")  # active, resolved, acknowledged
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class HealthCheckRequest(BaseModel):
    service_name: str
    endpoint: str
    timeout_seconds: int = 30
    expected_status: int = 200

class AlertRequest(BaseModel):
    service_name: str
    alert_type: str
    severity: str
    message: str
    metadata: Optional[Dict[str, Any]] = None

class ServiceStatus(BaseModel):
    service_name: str
    status: str
    response_time_ms: Optional[int] = None
    last_check: datetime
    error_message: Optional[str] = None

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def check_service_health(self, service_name: str, endpoint: str, timeout: int = 30):
    """Check health of a specific service"""
    start_time = time.time()
    
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(endpoint)
            
        response_time_ms = int((time.time() - start_time) * 1000)
        status = "healthy" if response.status_code == 200 else "unhealthy"
        
        # Store result in database
        with SessionLocal() as db:
            health_record = ServiceHealth(
                service_name=service_name,
                status=status,
                response_time_ms=response_time_ms,
                error_message=None if status == "healthy" else f"HTTP {response.status_code}"
            )
            db.add(health_record)
            db.commit()
        
        # Update metrics
        monitoring_checks_total.labels(service=service_name, status=status).inc()
        monitoring_check_duration.labels(service=service_name).observe(time.time() - start_time)
        service_health_status.labels(service=service_name).set(1 if status == "healthy" else 0)
        
        logger.info("Service health check completed", 
                   service=service_name, status=status, response_time_ms=response_time_ms)
        
        return {"status": status, "response_time_ms": response_time_ms}
        
    except Exception as e:
        logger.error("Service health check failed", service=service_name, error=str(e))
        
        # Store failure in database
        with SessionLocal() as db:
            health_record = ServiceHealth(
                service_name=service_name,
                status="unhealthy",
                response_time_ms=None,
                error_message=str(e)
            )
            db.add(health_record)
            db.commit()
        
        # Update metrics
        monitoring_checks_total.labels(service=service_name, status="unhealthy").inc()
        service_health_status.labels(service=service_name).set(0)
        
        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {"status": "unhealthy", "error": str(e)}

@celery_app.task
def cleanup_old_health_records():
    """Clean up old health check records"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
            deleted = db.execute(
                text("DELETE FROM service_health_new WHERE created_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            
        logger.info("Cleaned up old health records", deleted_count=deleted.rowcount)
        return {"deleted_count": deleted.rowcount}
        
    except Exception as e:
        logger.error("Failed to cleanup health records", error=str(e))
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
async def check_health(request: HealthCheckRequest, background_tasks: BackgroundTasks):
    """Initiate health check for a service"""
    try:
        # Queue health check task
        task = check_service_health.delay(
            request.service_name,
            request.endpoint,
            request.timeout_seconds
        )
        
        logger.info("Health check initiated", 
                   service=request.service_name, task_id=task.id)
        
        return {
            "task_id": task.id,
            "service_name": request.service_name,
            "status": "initiated"
        }
        
    except Exception as e:
        logger.error("Failed to initiate health check", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/monitoring/v4/services/{service_name}/status")
async def get_service_status(service_name: str):
    """Get current status of a service"""
    try:
        with SessionLocal() as db:
            latest_health = db.query(ServiceHealth).filter(
                ServiceHealth.service_name == service_name
            ).order_by(ServiceHealth.last_check.desc()).first()
            
            if not latest_health:
                raise HTTPException(status_code=404, detail="Service not found")
            
            return ServiceStatus(
                service_name=latest_health.service_name,
                status=latest_health.status,
                response_time_ms=latest_health.response_time_ms,
                last_check=latest_health.last_check,
                error_message=latest_health.error_message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get service status", service=service_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/monitoring/v4/services")
async def list_services():
    """List all monitored services"""
    try:
        with SessionLocal() as db:
            services = db.query(ServiceHealth).distinct(ServiceHealth.service_name).all()
            
            return [
                {
                    "service_name": service.service_name,
                    "last_status": service.status,
                    "last_check": service.last_check
                }
                for service in services
            ]
            
    except Exception as e:
        logger.error("Failed to list services", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/monitoring/v4/alerts")
async def create_alert(request: AlertRequest):
    """Create a new alert"""
    try:
        with SessionLocal() as db:
            alert = Alert(
                service_name=request.service_name,
                alert_type=request.alert_type,
                severity=request.severity,
                message=request.message,
                metadata=request.metadata
            )
            db.add(alert)
            db.commit()
            
            # Update metrics
            active_alerts.labels(severity=request.severity).inc()
            
        logger.info("Alert created", 
                   service=request.service_name, severity=request.severity)
        
        return {
            "alert_id": alert.id,
            "status": "created"
        }
        
    except Exception as e:
        logger.error("Failed to create alert", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/monitoring/v4/alerts")
async def list_alerts(
    service_name: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: str = Query("active")
):
    """List alerts with optional filtering"""
    try:
        with SessionLocal() as db:
            query = db.query(Alert).filter(Alert.status == status)
            
            if service_name:
                query = query.filter(Alert.service_name == service_name)
            if severity:
                query = query.filter(Alert.severity == severity)
                
            alerts = query.order_by(Alert.created_at.desc()).limit(100).all()
            
            return [
                {
                    "id": alert.id,
                    "service_name": alert.service_name,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "status": alert.status,
                    "created_at": alert.created_at,
                    "metadata": alert.metadata
                }
                for alert in alerts
            ]
            
    except Exception as e:
        logger.error("Failed to list alerts", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_health_check(self, service_name: str, service_url: str):
    """Process health check for a service (sync httpx client)"""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{service_url}/health")
            status = "healthy" if response.status_code == 200 else "unhealthy"
            monitoring_checks_total.labels(service=service_name, status=status).inc()
            logger.info("Health check completed", service=service_name, status=status)
    except Exception as e:
        logger.error("Failed to process health check", service=service_name, error=str(e))
        monitoring_checks_total.labels(service=service_name, status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_alert_notification(self, alert_id: str, notification_data: Dict[str, Any]):
    """Process alert notification asynchronously"""
    try:
        with SessionLocal() as db:
            # Get alert
            alert = db.query(Alert).filter(Alert.id == alert_id).first()
            if not alert:
                raise ValueError(f"Alert {alert_id} not found")
            
            # Process notification logic here
            logger.info(f"Processing alert notification for alert {alert_id}")
            
            # Update metrics
            monitoring_operations_total.labels(operation="notification", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process alert notification for alert {alert_id}: {e}")
        monitoring_operations_total.labels(operation="notification", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_monitoring_data(self):
    """Clean up old monitoring data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            
            # Clean up old alerts
            alert_result = db.execute(text("""
                DELETE FROM alerts_new 
                WHERE created_at < :cutoff_date AND status IN ('resolved', 'acknowledged')
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old metrics
            metric_result = db.execute(text("""
                DELETE FROM metrics_new 
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {alert_result.rowcount} old alerts and {metric_result.rowcount} old metrics")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old monitoring data: {e}")
        raise self.retry(exc=e, countdown=300)

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
