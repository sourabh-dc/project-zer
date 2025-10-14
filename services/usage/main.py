# services/usage/main.py - ZeroQue Usage Service V4.1
# Production-ready usage service with Celery, RabbitMQ, and comprehensive metrics

import os
import uuid
import time
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Query, Body, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker, relationship, Session
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

SERVICE_NAME = "usage"
SERVICE_VERSION = "4.1.0"

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "false").lower() == "true"

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context from JWT or API key"""
    # Try API key first
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
                "permissions": ["usage.create", "usage.view", "usage.admin"]
            }
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Try JWT
    if authorization and "Bearer " in authorization:
        try:
            import jwt
            token = authorization.replace("Bearer ", "")
            claims = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return claims
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid JWT")
    
    # Demo mode
    if ALLOW_DEMO:
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}
    
    raise HTTPException(status_code=401, detail="Authentication required")

def check_permission(user_context: Dict, permission: str) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or permission in permissions

def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set RLS context for database session"""
    try:
        db.rollback()
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
        if user_id:
            db.execute(text("SET app.current_user = :uid"), {"uid": user_id})
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {e}")
        db.rollback()

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()


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
    logger.warning("Celery config not found, using defaults")

# Prometheus metrics
usage_events_recorded = Counter('usage_events_recorded_total', 'Total usage events recorded', ['tenant_id', 'meter_code'])
usage_event_duration = Histogram('usage_event_duration_seconds', 'Usage event processing duration', ['operation'])
active_meters = Gauge('active_meters_total', 'Total active meters', ['tenant_id'])

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# Models
class UsageEvent(Base):
    __tablename__ = "usage_events_new"
    
    event_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=True)
    meter_code = Column(String(100), nullable=False)
    quantity = Column(Integer, default=1)
    metadata_json = Column(JSON, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    event_id = Column(String(255), primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    aggregate_id = Column(String(255), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    log_id = Column(String(255), primary_key=True)
    aggregate_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=False)
    changes = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


try:
    Base.metadata.create_all(engine)
except:
    pass

# Payloads
class UsageEventRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    meter_code: str
    quantity: int = 1
    metadata: Optional[Dict] = None



# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def store_outbox_event(db, event_type, tenant_id, entity_id, event_data):
    """Store event in outbox for reliable publishing"""
    evt = OutboxEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        event_type=event_type,
        aggregate_id=tenant_id,
        event_data=json.dumps(event_data),
        retry_count=0,
        status="pending"
    )
    db.add(evt)
    db.commit()
    return str(evt.event_id)

def publish_to_rabbitmq(event_type: str, event_data: Dict, tenant_id: str):
    """Publish event to RabbitMQ"""
    try:
        conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        ch = conn.channel()
        ch.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        msg = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        ch.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=msg,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        conn.close()
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False

def audit_log(db, tenant_id, user_id, action, entity_type, entity_id, changes=None):
    """Create audit log entry"""
    try:
        log = AuditLog(
            log_id=f"aud_{uuid.uuid4().hex[:12]}",
            aggregate_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Audit failed: {e}")

# =============================================================================
# SAGA PATTERN
# =============================================================================

class UsageRecordSaga:
    """Saga for usage event recording with compensation"""

    def __init__(self, db):
        self.db = db
        self.event = None
        self.eid = None

    async def exec(self, event_id, tenant_id, req, uctx):
        """Execute usage recording saga"""
        start = time.time()
        try:
            # Check permissions
            if not check_permission(uctx, "usage.create"):
                raise ValueError("Insufficient permissions")

            # Create usage event
            self.event = UsageEvent(
                event_id=event_id,
                tenant_id=tenant_id,
                user_id=uctx.get("user_id"),
                meter_code=req.meter_code,
                quantity=req.quantity,
                metadata_json=req.metadata
            )
            self.db.add(self.event)
            self.db.commit()
            self.db.refresh(self.event)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "USAGE_RECORDED", tenant_id, event_id, {
                "event_id": event_id,
                "meter_code": req.meter_code,
                "quantity": req.quantity
            })

            # Publish event
            publish_to_rabbitmq("USAGE_RECORDED", {
                "event_id": event_id,
                "meter_code": req.meter_code,
                "quantity": req.quantity
            }, tenant_id)

            # Audit log
            audit_log(self.db, tenant_id, uctx.get("user_id"), "CREATE", "usage_event", event_id, {
                "meter_code": req.meter_code,
                "quantity": req.quantity
            })

            saga_total.labels(type="usage", status="ok").inc()
            saga_duration.labels(type="usage").observe(time.time() - start)
            return {"event_id": event_id, "recorded": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="usage", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.event:
                self.db.delete(self.event)
                self.db.commit()
        except Exception as e:
            logger.error(f"Usage compensation failed: {e}")
            self.db.rollback()


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="ZeroQue Usage Service", version=SERVICE_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Endpoints
@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.post("/usage/v4/record")
async def record_usage(request: UsageEventRequest):
    """Record a usage event"""
    try:
        event_id = f"usage_{uuid.uuid4().hex[:12]}"
        
        with SessionLocal() as db:
            event = UsageEvent(
                event_id=event_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                meter_code=request.meter_code,
                quantity=request.quantity,
                metadata_json=request.metadata
            )
            db.add(event)
            db.commit()
        
        logger.info(f"Usage recorded: {event_id}")
        
        return {
            "event_id": event_id,
            "tenant_id": request.tenant_id,
            "meter_code": request.meter_code,
            "quantity": request.quantity,
            "recorded": True
        }
    
    except Exception as e:
        logger.error(f"Usage recording failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/usage/v4/events")
async def get_usage_events(tenant_id: str = Query(...), limit: int = Query(100), uctx: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    """Get usage events for a tenant"""
    try:
        if not check_permission(uctx, "usage.view"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        events = db.query(UsageEvent).filter(
            UsageEvent.tenant_id == tenant_id
        ).order_by(UsageEvent.recorded_at.desc()).limit(limit).all()
        
        return [{
            "event_id": e.event_id,
            "meter_code": e.meter_code,
            "quantity": e.quantity,
            "recorded_at": e.recorded_at.isoformat()
        } for e in events]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(name='usage.publish_outbox_events')
def publish_outbox_events():
    """Publish outbox events to RabbitMQ"""
    try:
        with SessionLocal() as db:
            evts = db.query(OutboxEvent).filter(
                OutboxEvent.status == "pending",
                OutboxEvent.retry_count < 5
            ).limit(100).all()
            
            for e in evts:
                event_data = json.loads(e.event_data) if isinstance(e.event_data, str) else e.event_data
                if publish_to_rabbitmq(e.event_type, event_data, e.aggregate_id):
                    e.status = "published"
                    e.published_at = datetime.now(timezone.utc)
                else:
                    e.retry_count += 1
                    if e.retry_count >= 5:
                        e.status = "failed"
                db.commit()
            
            if evts:
                logger.info(f"Published {len(evts)} events")
    except Exception as ex:
        logger.error(f"Outbox publish failed: {ex}")

@celery_app.task(bind=True, max_retries=3, name='usage.cleanup_old_usage_events')
def cleanup_old_usage_events(self):
    """Clean up old usage events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM usage_events_new WHERE recorded_at < :cutoff"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f"Cleaned {result.rowcount} old usage events")
            return {'deleted': result.rowcount}
    except Exception as e:
        logger.error(f"Failed to cleanup usage events: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='usage.cleanup_old_outbox_events')
def cleanup_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            result = db.execute(
                text("DELETE FROM outbox_events WHERE created_at < :cutoff AND status IN ('published', 'failed')"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f"Cleaned {result.rowcount} old outbox events")
            return {'deleted': result.rowcount}
    except Exception as e:
        logger.error(f"Failed to cleanup outbox events: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(name='usage.process_entry_granted')
def process_entry_granted(event_data: Dict):
    """Process ENTRY_GRANTED event"""
    try:
        tenant_id = event_data.get('tenant_id')
        user_id = event_data.get('user_id')
        
        if tenant_id:
            with SessionLocal() as db:
                # Record entry as usage event
                event_id = f"usage_{uuid.uuid4().hex[:12]}"
                event = UsageEvent(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    meter_code='entry_count',
                    quantity=1,
                    metadata_json={"source": "entry_service"}
                )
                db.add(event)
                db.commit()
                logger.info(f"Recorded entry usage for tenant {tenant_id}")
        
        return {'status': 'ok'}
    except Exception as e:
        logger.error(f"Failed to process ENTRY_GRANTED: {e}")
        return {'status': 'error'}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8200")))
    uvicorn.run(app, host="0.0.0.0", port=port)
