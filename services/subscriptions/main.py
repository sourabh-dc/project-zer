# services/subscriptions/main.py - ZeroQue Subscriptions Service v4.1 (Production-Ready)
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
from sqlalchemy import create_engine, text, Column, String, Integer, BigInteger, Boolean, DateTime, func, JSON, Text, ForeignKey
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
SERVICE_NAME = "subscriptions"
SERVICE_VERSION = "4.1.0"
SUBSCRIPTION_CLEANUP_DAYS = 365
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
sub_requests_total = Counter('sub_requests_total', 'Requests', ['endpoint', 'status'])
sub_request_duration = Histogram('sub_request_duration_seconds', 'Duration', ['endpoint'])
saga_total = Counter('sub_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('sub_saga_duration_seconds', 'Saga duration', ['type'])

# Circuit Breaker
circuit_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)

# Models
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price_yearly_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), default="GBP", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Feature(Base):
    __tablename__ = "features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PlanFeature(Base):
    __tablename__ = "plan_features"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code"), nullable=False)
    feature_code = Column(String(50), ForeignKey("features.code"), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    limits = Column(JSON, nullable=True)  # e.g., {"rate_limit": 1000} or {"tier": "basic"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), unique=True, index=True, nullable=False)
    plan_code = Column(String(50), ForeignKey("subscription_plans.code"), nullable=False)
    payment_method = Column(String(20), nullable=False)
    status = Column(String(50), default="active", nullable=False)
    external_id = Column(String(100), index=True, nullable=True)
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    trial_end = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class SiteBillingAccount(Base):
    __tablename__ = "site_billing_accounts"
    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), index=True, nullable=False)
    site_id = Column(SQLUUID(as_uuid=True), index=True, nullable=False)
    payment_method = Column(String(20), nullable=False)
    external_id = Column(String(100), index=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    account_metadata = Column(JSON, nullable=True)
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
class TenantSubscriptionPayload(BaseModel):
    plan_code: str = Field(..., description="Subscription plan code")
    payment_method: str = Field(..., description="Payment method: stripe, trade")
    external_id: Optional[str] = Field(None, description="External subscription ID")
    current_period_start: Optional[datetime] = Field(None)
    current_period_end: Optional[datetime] = Field(None)
    trial_end: Optional[datetime] = Field(None)

class CreateBillingAccountPayload(BaseModel):
    site_id: str = Field(..., description="Site ID")
    payment_method: str = Field(..., description="Payment method: stripe, trade")
    external_id: str = Field(..., description="External billing account ID")
    metadata: Optional[Dict[str, Any]] = Field(None)

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

# Saga for Subscription Creation
class SubscriptionSaga:
    def __init__(self, db: Session):
        self.db = db
        self.subscription = None
        self.outbox_id = None
    
    async def execute(self, tenant_id: str, payload: TenantSubscriptionPayload, user_context: Dict[str, Any]) -> Dict:
        start_time = time.time()
        try:
            # Step 1: Validate
            if self.db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first():
                raise ValueError("Subscription exists")
            
            # Step 2: Create subscription
            self.subscription = TenantSubscription(
                tenant_id=tenant_id,
                plan_code=payload.plan_code,
                payment_method=payload.payment_method,
                status="active",
                external_id=payload.external_id or f"sub_{tenant_id}_{int(time.time())}",
                current_period_start=payload.current_period_start or datetime.now(),
                current_period_end=payload.current_period_end or (datetime.now() + timedelta(days=365)),
                trial_end=payload.trial_end
            )
            self.db.add(self.subscription)
            self.db.commit()
            self.db.refresh(self.subscription)
            
            # Step 3: Store outbox event
            self.outbox_id = store_outbox_event(self.db, "PLAN_CREATED", tenant_id, str(self.subscription.id), {
                "tenant_id": tenant_id,
                "plan_code": payload.plan_code,
                "subscription_id": str(self.subscription.id)
            })
            
            # Step 4: Publish event
            publish_outbox_events.delay()
            
            # Audit log
            audit_log(self.db, tenant_id, user_context.get("user_id"), "CREATE", "subscription", str(self.subscription.id), payload.dict())
            
            saga_total.labels(type="subscription", status="success").inc()
            saga_duration.labels(type="subscription").observe(time.time() - start_time)
            
            return {"subscription_id": str(self.subscription.id), "plan_code": payload.plan_code, "created": True}
        
        except Exception as e:
            await self.compensate()
            saga_total.labels(type="subscription", status="failed").inc()
            raise
    
    async def compensate(self):
        try:
            if self.outbox_id:
                self.db.execute(text("DELETE FROM outbox_events WHERE id = :id"), {"id": self.outbox_id})
                self.db.commit()
            
            if self.subscription:
                self.db.delete(self.subscription)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()

# Celery Worker for TENANT_CREATED
@celery_app.task(name='subscriptions.process_tenant_created')
def process_tenant_created(event_data: Dict):
    try:
        tenant_id = event_data['tenant_id']
        with SessionLocal() as db:
            # Auto-create default subscription (e.g., Core plan)
            subscription = TenantSubscription(
                tenant_id=tenant_id,
                plan_code="core",
                payment_method="trade",
                status="active",
                external_id=f"sub_{tenant_id}_{int(time.time())}",
                current_period_start=datetime.now(),
                current_period_end=datetime.now() + timedelta(days=365)
            )
            db.add(subscription)
            db.commit()
            logger.info(f"Auto-created Core subscription for tenant {tenant_id}")
            # Publish PLAN_CREATED
            store_outbox_event(db, "PLAN_CREATED", tenant_id, tenant_id, {"tenant_id": tenant_id, "plan_code": "core"})
            publish_outbox_events.delay()
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED: {e}")
        raise

@celery_app.task(name='subscriptions.cleanup_old_subscriptions')
def cleanup_old_subscriptions():
    try:
        with SessionLocal() as db:
            cutoff = datetime.now() - timedelta(days=SUBSCRIPTION_CLEANUP_DAYS)
            deleted = db.execute(text("DELETE FROM tenant_subscriptions WHERE canceled_at < :cutoff AND status = 'canceled'"), {"cutoff": cutoff})
            db.commit()
            logger.info(f"Cleaned {deleted.rowcount} old subscriptions")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")

# App Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Subscriptions Service v4.1")
    init_db()
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down Subscriptions Service v4.1")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app = FastAPI(
    title="ZeroQue Subscriptions Service",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Health
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

# Endpoints
@app.get("/subscriptions/v2/plans")
def list_plans(active: Optional[bool] = Query(None)):
    with SessionLocal() as db:
        query = db.query(SubscriptionPlan)
        if active is not None:
            query = query.filter(SubscriptionPlan.active == active)
        plans = query.all()
        return [{"code": p.code, "name": p.name, "price_yearly_minor": p.price_yearly_minor} for p in plans]

@app.get("/subscriptions/v2/plans/{plan_code}/features")
def list_plan_features(plan_code: str):
    with SessionLocal() as db:
        features = db.query(PlanFeature, Feature).join(Feature).filter(PlanFeature.plan_code == plan_code).all()
        return [{"feature_code": pf.feature_code, "limits": pf.limits or {}} for pf, f in features]

@app.post("/subscriptions/v2/subscriptions")
async def create_subscription(tenant_id: str = Body(...), payload: TenantSubscriptionPayload = Body(...), user_context: Dict = Depends(get_user_context)):
    try:
        if not check_permission("subscriptions.create", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            set_rls_context(db, user_context["tenant_id"])
            
            saga = SubscriptionSaga(db)
            result = await saga.execute(tenant_id, payload, user_context)
            
            return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subscriptions/v2/subscriptions/{tenant_id}")
def get_subscription(tenant_id: str):
    with SessionLocal() as db:
        subscription = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {"plan_code": subscription.plan_code, "status": subscription.status}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)