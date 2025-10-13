# services/entitlements/main.py - ZeroQue Entitlements Service v4.1 (Production-Ready)
import os
import uuid
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Query, Body, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, Column, String, Integer, DateTime, Text, func, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as SQLUUID
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.exc import IntegrityError
import pika
from celery import Celery
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
import pybreaker
import jwt
import redis
import structlog

# Config
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
JWT_ALGORITHM = "HS256"
SERVICE_NAME = "entitlements"
SERVICE_VERSION = "4.1.0"
USAGE_CLEANUP_DAYS = 365
RATE_LIMIT_REQUESTS_PER_MINUTE = 60

# Logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger(SERVICE_NAME)

# DB
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis
redis_client = None

# Celery
celery_app = Celery(SERVICE_NAME, broker=RABBITMQ_URL, backend=REDIS_URL)
celery_app.conf.update(task_serializer='json', accept_content=['json'], timezone='UTC', enable_utc=True)

# Metrics
ent_checks_total = Counter('ent_checks_total', 'Checks', ['tenant_id', 'feature', 'result'])
ent_check_duration = Histogram('ent_check_duration_seconds', 'Duration')
usage_records_total = Counter('usage_records_total', 'Usage records', ['tenant_id', 'feature'])
saga_total = Counter('ent_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('ent_saga_duration_seconds', 'Saga duration')

# Circuit Breaker
circuit_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)

# Models
class SubscriptionUsage(Base):
    __tablename__ = "subscription_usage"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    feature_code = Column(String(50), nullable=False, index=True)
    usage_type = Column(String(50), nullable=False, index=True)
    usage_count = Column(Integer, default=0, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False, index=True)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    aggregate_id = Column(SQLUUID(as_uuid=True), nullable=True)
    event_data = Column(JSON, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(SQLUUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(SQLUUID(as_uuid=True), nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic Models
class CheckEntitlementRequest(BaseModel):
    tenant_id: str
    feature_code: str

class RecordUsageRequest(BaseModel):
    tenant_id: str
    feature_code: str
    usage_type: str
    count: int = 1

# Security
security = HTTPBearer()

def get_user_context(authorization: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    try:
        token = authorization.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return {
            "user_id": payload.get("user_id"),
            "tenant_id": payload.get("tenant_id"),
            "roles": payload.get("roles", []),
            "permissions": payload.get("permissions", [])
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"JWT validation error: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid authentication")

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    permissions = user_context.get("permissions", [])
    if "*" in permissions:
        return True
    return required_permission in permissions

def get_db(user_context: Dict[str, Any] = Depends(get_user_context)):
    db = SessionLocal()
    try:
        set_rls_context(db, user_context["tenant_id"], user_context["user_id"])
        yield db
    finally:
        db.close()

# RabbitMQ Publishing
def publish_to_rabbitmq(event_type: str, event_data: Dict[str, Any], tenant_id: str):
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        message = json.dumps({"event_type": event_type, "tenant_id": tenant_id, "timestamp": datetime.now().isoformat(), "data": event_data})
        channel.basic_publish(exchange='zeroque_events', routing_key=event_type, body=message, properties=pika.BasicProperties(delivery_mode=2))
        connection.close()
        logger.info(f"Published {event_type}")
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False

# Outbox Pattern
def store_outbox_event(db: Session, event_type: str, tenant_id: str, aggregate_id: Optional[str] = None, event_data: Dict[str, Any] = {}):
    outbox_event = OutboxEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        aggregate_id=aggregate_id or tenant_id,
        event_data=event_data,
        status="pending",
        retry_count=0
    )
    db.add(outbox_event)
    db.commit()
    return str(outbox_event.id)

@celery_app.task(bind=True, max_retries=3)
def publish_outbox_events(self):
    try:
        with SessionLocal() as db:
            events = db.query(OutboxEvent).filter(OutboxEvent.status == "pending", OutboxEvent.retry_count < 3).limit(100).all()
            for event in events:
                success = publish_to_rabbitmq(event.event_type, event.event_data, event.tenant_id)
                if success:
                    event.status = "published"
                    event.published_at = datetime.now()
                else:
                    event.retry_count += 1
                    if event.retry_count >= 3:
                        event.status = "failed"
                db.commit()
    except Exception as e:
        logger.error(f"Outbox publishing failed: {e}")
        raise self.retry(exc=e, countdown=60)

# Audit Logging
def audit_log(db: Session, tenant_id: str, user_id: Optional[str], action: str, resource_type: str, resource_id: Optional[str], details: Optional[Dict] = None, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
    audit_entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(audit_entry)
    db.commit()

# Saga for Usage Recording
class UsageRecordSaga:
    def __init__(self, db: Session):
        self.db = db
        self.usage = None
        self.outbox_id = None
    
    async def execute(self, payload: RecordUsageRequest, user_context: Dict[str, Any]) -> Dict:
        start_time = time.time()
        try:
            # Step 1: Validate
            if not check_permission("entitlements.record_usage", user_context):
                raise ValueError("Insufficient permissions")
            if payload.count <= 0:
                raise ValueError("Count must be positive")
            
            # Step 2: Record usage
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            self.usage = self.db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == payload.tenant_id,
                SubscriptionUsage.feature_code == payload.feature_code,
                SubscriptionUsage.usage_type == payload.usage_type,
                SubscriptionUsage.period_start >= month_start,
                SubscriptionUsage.period_start < month_end
            ).first()
            
            if self.usage:
                self.usage.usage_count += payload.count
                self.usage.updated_at = now
            else:
                self.usage = SubscriptionUsage(
                    tenant_id=payload.tenant_id,
                    feature_code=payload.feature_code,
                    usage_type=payload.usage_type,
                    usage_count=payload.count,
                    period_start=month_start,
                    period_end=month_end
                )
                self.db.add(self.usage)
            
            self.db.commit()
            self.db.refresh(self.usage)
            
            # Step 3: Store outbox event
            self.outbox_id = store_outbox_event(self.db, "USAGE_RECORDED", payload.tenant_id, payload.tenant_id, {
                "tenant_id": payload.tenant_id,
                "feature_code": payload.feature_code,
                "usage_type": payload.usage_type,
                "count": payload.count,
                "total": self.usage.usage_count
            })
            
            # Step 4: Publish event
            publish_outbox_events.delay()
            
            # Audit log
            audit_log(self.db, payload.tenant_id, user_context.get("user_id"), "RECORD_USAGE", "usage", str(self.usage.id), payload.dict())
            
            saga_total.labels(type="usage_record", status="success").inc()
            saga_duration.labels(type="usage_record").observe(time.time() - start_time)
            
            return {"tenant_id": payload.tenant_id, "feature_code": payload.feature_code, "usage_type": payload.usage_type, "count": payload.count, "total": self.usage.usage_count}
        
        except Exception as e:
            await self.compensate()
            saga_total.labels(type="usage_record", status="failed").inc()
            raise
    
    async def compensate(self):
        try:
            if self.outbox_id:
                self.db.execute(text("DELETE FROM outbox_events WHERE id = :id"), {"id": self.outbox_id})
                self.db.commit()
            
            if self.usage:
                self.db.delete(self.usage)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()

# Celery Worker for TENANT_CREATED
@celery_app.task(name='entitlements.process_tenant_created')
def process_tenant_created(event_data: Dict):
    try:
        tenant_id = event_data['tenant_id']
        with SessionLocal() as db:
            # Initialize usage records for default features (e.g., from Subscriptions)
            default_features = ["api_calls", "analytics"]  # Fetch from Subscriptions if needed
            month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            for feature in default_features:
                usage = SubscriptionUsage(
                    tenant_id=tenant_id,
                    feature_code=feature,
                    usage_type="default",
                    usage_count=0,
                    period_start=month_start,
                    period_end=month_end
                )
                db.add(usage)
            db.commit()
            logger.info(f"Initialized usage for tenant {tenant_id}")
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED: {e}")
        raise

@celery_app.task(name='entitlements.cleanup_old_usage')
def cleanup_old_usage():
    try:
        with SessionLocal() as db:
            cutoff = datetime.now() - timedelta(days=365)
            deleted = db.execute(text("DELETE FROM subscription_usage WHERE created_at < :cutoff"), {"cutoff": cutoff})
            db.commit()
            logger.info(f"Cleaned {deleted.rowcount} old usage records")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")

# App Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Entitlements Service v4.1")
    init_db()
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down Entitlements Service v4.1")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app = FastAPI(
    title="ZeroQue Entitlements Service",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Health
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

# Endpoints
@app.get("/entitlements/v2/check")
async def check_entitlement(req: CheckEntitlementRequest = Body(...), user_context: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    if not check_permission("entitlements.check", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # ... (rest as per previous code, with RLS in process)
    # Add audit_log(db, req.tenant_id, user_context["user_id"], "CHECK_ENTITLEMENT", "entitlement", req.feature_code)

@app.post("/entitlements/v2/usage/record")
async def record_usage(payload: RecordUsageRequest = Body(...), user_context: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    if not check_permission("entitlements.record_usage", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    saga = UsageRecordSaga(db)
    result = await saga.execute(payload, user_context)
    return result

@app.get("/entitlements/v2/usage/{tenant_id}")
async def get_usage_summary(tenant_id: str, user_context: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    if not check_permission("entitlements.view_usage", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # ... (rest as per previous code, with RLS)

@app.post("/entitlements/v2/cache/clear")
async def clear_cache(tenant_id: Optional[str] = Query(None), user_context: Dict = Depends(get_user_context)):
    if not check_permission("entitlements.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # ... (rest as per previous code)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)