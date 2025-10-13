# services/observability/main.py - ZeroQue Observability Service V4.1
# Production-ready observability service with Celery, RabbitMQ, and comprehensive metrics

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

SERVICE_NAME = "observability"
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
observability_requests_total = Counter('observability_requests_total', 'Total observability requests', ['endpoint', 'status'])
observability_request_duration = Histogram('observability_request_duration_seconds', 'Observability request duration', ['endpoint'])
system_metrics_collected = Counter('system_metrics_collected_total', 'Total system metrics collected', ['metric_type'])
active_monitors = Gauge('active_monitors_total', 'Total active monitors', ['monitor_type'])

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# Define missing metrics and helper used in Celery tasks
observability_operations_total = Counter('observability_operations_total', 'Observability operations processed', ['operation', 'status'])

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

class Metric(Base):
    __tablename__ = "metrics_new"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    metric_name = Column(String, nullable=False)
    metric_type = Column(String, nullable=False)  # counter, gauge, histogram, summary
    value = Column(Numeric, nullable=False)
    labels = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    tenant_id = Column(String, nullable=True)
    service_name = Column(String, nullable=True)

class Monitor(Base):
    __tablename__ = "monitors_new"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    monitor_name = Column(String, nullable=False)
    monitor_type = Column(String, nullable=False)  # health, performance, error_rate
    target_service = Column(String, nullable=False)
    target_endpoint = Column(String, nullable=False)
    check_interval_seconds = Column(Integer, nullable=False, default=60)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    threshold_value = Column(Numeric, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_check = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, nullable=True)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class MetricRequest(BaseModel):
    metric_name: str
    metric_type: str
    value: float
    labels: Optional[Dict[str, str]] = None
    tenant_id: Optional[str] = None
    service_name: Optional[str] = None

class MonitorRequest(BaseModel):
    monitor_name: str
    monitor_type: str
    target_service: str
    target_endpoint: str
    check_interval_seconds: int = 60
    timeout_seconds: int = 30
    threshold_value: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

class SystemMetrics(BaseModel):
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    network_bytes_sent: int
    network_bytes_received: int
    timestamp: datetime

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def collect_system_metrics(self):
    """Collect system metrics"""
    try:
        import psutil
        
        # Collect system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()
        
        metrics_data = {
            "cpu_usage_percent": cpu_percent,
            "memory_usage_percent": memory.percent,
            "disk_usage_percent": (disk.used / disk.total) * 100,
            "network_bytes_sent": network.bytes_sent,
            "network_bytes_received": network.bytes_recv,
            "timestamp": datetime.now(timezone.utc)
        }
        
        # Store metrics in database
        with SessionLocal() as db:
            for metric_name, value in metrics_data.items():
                if metric_name != "timestamp":
                    metric = Metric(
                        metric_name=metric_name,
                        metric_type="gauge",
                        value=value,
                        labels={"source": "system"},
                        service_name=SERVICE_NAME
                    )
                    db.add(metric)
            db.commit()
        
        # Update Prometheus metrics
        system_metrics_collected.labels(metric_type="system").inc()
        
        logger.info("System metrics collected", **metrics_data)
        return metrics_data
        
    except Exception as e:
        logger.error("Failed to collect system metrics", error=str(e))
        
        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {"error": str(e)}

@celery_app.task(bind=True, max_retries=3)
def run_monitor_check(self, monitor_id: str):
    """Run a specific monitor check"""
    try:
        with SessionLocal() as db:
            monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
            if not monitor:
                logger.error("Monitor not found", monitor_id=monitor_id)
                return {"error": "Monitor not found"}
            
            if not monitor.is_active:
                logger.info("Monitor is inactive", monitor_id=monitor_id)
                return {"status": "inactive"}
            
            # Perform health check
            start_time = time.time()
            try:
                with httpx.Client(timeout=monitor.timeout_seconds) as client:
                    response = client.get(monitor.target_endpoint)
                
                response_time = time.time() - start_time
                status = "healthy" if response.status_code == 200 else "unhealthy"
                
                # Store result
                monitor.last_check = datetime.now(timezone.utc)
                monitor.last_status = status
                db.commit()
                
                # Update metrics
                active_monitors.labels(monitor_type=monitor.monitor_type).set(1)
                
                logger.info("Monitor check completed", 
                           monitor_id=monitor_id, status=status, response_time=response_time)
                
                return {
                    "monitor_id": monitor_id,
                    "status": status,
                    "response_time": response_time,
                    "response_code": response.status_code
                }
                
            except Exception as e:
                monitor.last_check = datetime.now(timezone.utc)
                monitor.last_status = "error"
                db.commit()
                
                logger.error("Monitor check failed", monitor_id=monitor_id, error=str(e))
                
                # Retry if not exceeded max retries
                if self.request.retries < self.max_retries:
                    raise self.retry(countdown=60 * (2 ** self.request.retries))
                
                return {"status": "error", "error": str(e)}
                
    except Exception as e:
        logger.error("Failed to run monitor check", monitor_id=monitor_id, error=str(e))
        return {"error": str(e)}

@celery_app.task
def cleanup_old_metrics():
    """Clean up old metrics"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            deleted = db.execute(
                text("DELETE FROM metrics_new WHERE timestamp < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            
        logger.info("Cleaned up old metrics", deleted_count=deleted.rowcount)
        return {"deleted_count": deleted.rowcount}
        
    except Exception as e:
        logger.error("Failed to cleanup metrics", error=str(e))
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
    try:
        with SessionLocal() as db:
            metric = Metric(
                metric_name=request.metric_name,
                metric_type=request.metric_type,
                value=request.value,
                labels=request.labels,
                tenant_id=request.tenant_id,
                service_name=request.service_name
            )
            db.add(metric)
            db.commit()
            
            # Update Prometheus metrics
            observability_requests_total.labels(endpoint="record_metric", status="success").inc()
            
        logger.info("Metric recorded", 
                   metric_name=request.metric_name, value=request.value)
        
        return {
            "metric_id": metric.id,
            "status": "recorded"
        }
        
    except Exception as e:
        logger.error("Failed to record metric", error=str(e))
        observability_requests_total.labels(endpoint="record_metric", status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/observability/v4/metrics")
async def get_metrics(
    metric_name: Optional[str] = Query(None),
    service_name: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """Get metrics with optional filtering"""
    try:
        with SessionLocal() as db:
            query = db.query(Metric)
            
            if metric_name:
                query = query.filter(Metric.metric_name == metric_name)
            if service_name:
                query = query.filter(Metric.service_name == service_name)
                
            metrics = query.order_by(Metric.timestamp.desc()).limit(limit).all()
            
            return [
                {
                    "id": metric.id,
                    "metric_name": metric.metric_name,
                    "metric_type": metric.metric_type,
                    "value": float(metric.value),
                    "labels": metric.labels,
                    "timestamp": metric.timestamp,
                    "tenant_id": metric.tenant_id,
                    "service_name": metric.service_name
                }
                for metric in metrics
            ]
            
    except Exception as e:
        logger.error("Failed to get metrics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/observability/v4/monitors")
async def create_monitor(request: MonitorRequest):
    """Create a new monitor"""
    try:
        with SessionLocal() as db:
            monitor = Monitor(
                monitor_name=request.monitor_name,
                monitor_type=request.monitor_type,
                target_service=request.target_service,
                target_endpoint=request.target_endpoint,
                check_interval_seconds=request.check_interval_seconds,
                timeout_seconds=request.timeout_seconds,
                threshold_value=request.threshold_value,
                metadata=request.metadata
            )
            db.add(monitor)
            db.commit()
            
            # Update metrics
            active_monitors.labels(monitor_type=request.monitor_type).inc()
            
        logger.info("Monitor created", 
                   monitor_name=request.monitor_name, monitor_type=request.monitor_type)
        
        return {
            "monitor_id": monitor.id,
            "status": "created"
        }
        
    except Exception as e:
        logger.error("Failed to create monitor", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/observability/v4/monitors")
async def list_monitors():
    """List all monitors"""
    try:
        with SessionLocal() as db:
            monitors = db.query(Monitor).order_by(Monitor.created_at.desc()).all()
            
            return [
                {
                    "id": monitor.id,
                    "monitor_name": monitor.monitor_name,
                    "monitor_type": monitor.monitor_type,
                    "target_service": monitor.target_service,
                    "target_endpoint": monitor.target_endpoint,
                    "is_active": monitor.is_active,
                    "last_check": monitor.last_check,
                    "last_status": monitor.last_status,
                    "created_at": monitor.created_at
                }
                for monitor in monitors
            ]
            
    except Exception as e:
        logger.error("Failed to list monitors", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

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
async def get_system_metrics():
    """Get current system metrics"""
    try:
        import psutil
        
        # Get current system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()
        
        return SystemMetrics(
            cpu_usage_percent=cpu_percent,
            memory_usage_percent=memory.percent,
            disk_usage_percent=(disk.used / disk.total) * 100,
            network_bytes_sent=network.bytes_sent,
            network_bytes_received=network.bytes_recv,
            timestamp=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        logger.error("Failed to get system metrics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def collect_system_metrics(self):
    """Collect system metrics asynchronously"""
    try:
        import psutil
        
        # Collect system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()
        
        # Store metrics in database
        with SessionLocal() as db:
            metrics = SystemMetrics(
                cpu_usage_percent=cpu_percent,
                memory_usage_percent=memory.percent,
                disk_usage_percent=(disk.used / disk.total) * 100,
                network_bytes_sent=network.bytes_sent,
                network_bytes_received=network.bytes_recv,
                timestamp=datetime.now(timezone.utc)
            )
            
            db.add(metrics)
            db.commit()
            
            # Update metrics
            observability_operations_total.labels(operation="metrics_collection", status="success").inc()
            
            logger.info(f"System metrics collected successfully")
            
    except Exception as e:
        logger.error(f"Failed to collect system metrics: {e}")
        observability_operations_total.labels(operation="metrics_collection", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_log_aggregation(self, tenant_id: str, log_data: Dict[str, Any]):
    """Process log aggregation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process log aggregation logic here
            logger.info(f"Processing log aggregation for tenant {tenant_id}")
            
            # Update metrics
            observability_operations_total.labels(operation="log_aggregation", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process log aggregation for tenant {tenant_id}: {e}")
        observability_operations_total.labels(operation="log_aggregation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_observability_data(self):
    """Clean up old observability data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            
            # Clean up old system metrics
            metrics_result = db.execute(text("""
                DELETE FROM system_metrics_new 
                WHERE timestamp < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old log entries
            log_result = db.execute(text("""
                DELETE FROM log_entries_new 
                WHERE timestamp < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {metrics_result.rowcount} old system metrics and {log_result.rowcount} old log entries")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old observability data: {e}")
        raise self.retry(exc=e, countdown=300)

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
