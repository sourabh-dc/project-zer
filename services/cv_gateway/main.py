# CV Gateway Service - Enhanced V4.1 Architecture
# Multi-provider CV order processing with sagas, events, and RLS

import os
import uuid
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body, HTTPException, Query, Path, Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

# Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Database imports
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
import jwt

# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Metrics for CV Gateway (temporarily disabled to avoid conflicts)
class MetricStub:
    def labels(self, **kwargs):
        return self
    def inc(self): pass
    def observe(self, val): pass

cv_gateway_requests_total = MetricStub()
cv_gateway_request_duration = MetricStub()
cv_order_processing_total = MetricStub()
cv_order_processing_duration = MetricStub()
cv_saga_steps_total = MetricStub()
cv_unknown_items_total = MetricStub()

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "cv_gateway"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "true").lower() == "true"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
JWT_ALGORITHM = "HS256"
RATE_LIMIT_REQUESTS_PER_MINUTE = 60
MAX_REQUEST_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

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

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

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
# Minimal helper stubs to prevent runtime NameErrors in this standalone service
def get_engine():
    return engine

def init_db():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

def add_api_call_meter(app):
    return app

def add_idempotency_middleware(app, routes=None):
    return app

def check_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def create_trade_invoice_if_applicable(db, tenant_id: str, order_id: int, total_minor: int, currency: str, site_id: str, store_id: str):
    # Placeholder hook for billing integration
    return None

# =============================================================================
# DATABASE MODELS
# =============================================================================

class Device(Base):
    """Phase 2: Device registry for hardware monitoring"""
    __tablename__ = "devices"
    
    device_id = Column(String(100), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    device_type = Column(String(50), nullable=False)  # camera, sensor, entry_device
    device_name = Column(String(255), nullable=False)
    zone = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default='online')  # online, offline, error, maintenance
    health_score = Column(Integer, nullable=True)  # 0-100
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    device_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class DeviceStatusLog(Base):
    """Phase 2: Device status change logs"""
    __tablename__ = "device_status_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    health_score = Column(Integer, nullable=True)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class DeviceAlert(Base):
    """Phase 2: Device alerts for offline/error states"""
    __tablename__ = "device_alerts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False)  # offline, error, low_health
    severity = Column(String(20), nullable=False, default='warning')  # info, warning, critical
    message = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='open')  # open, acknowledged, resolved
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class CvUnknownItemReview(Base):
    """Unknown item reviews for reconciliation"""
    __tablename__ = "cv_unknown_item_reviews"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey('sites.site_id'), nullable=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey('stores.store_id'), nullable=True)
    provider = Column(String(50), nullable=False)
    external_sku = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    qty = Column(Integer, nullable=False)
    price_minor = Column(Integer, nullable=False)
    payload_json = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    mapped_sku = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OutboxEvent(Base):
    """Reliable event publishing"""
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AuditLog(Base):
    """Audit trail for operations"""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id'), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class AiFiItem(BaseModel):
    """CV order item"""
    sku: str = Field(..., description="Product SKU")
    name: str = Field(..., description="Product name")
    qty: int = Field(..., description="Quantity")
    price_minor: int = Field(..., description="Price in minor units")

class AiFiOrder(BaseModel):
    """CV order from provider"""
    provider: str = Field(..., description="Provider name")
    provider_order_id: str = Field(..., description="Provider order ID")
    
    # External IDs (optional if local IDs are provided)
    tenant_ext_id: Optional[str] = Field(None, description="External tenant ID")
    site_ext_id: Optional[str] = Field(None, description="External site ID")
    store_ext_id: Optional[str] = Field(None, description="External store ID")
    user_ext_id: Optional[str] = Field(None, description="External user ID")
    
    # Local IDs (preferred)
    tenant_id: Optional[str] = Field(None, description="Local tenant ID")
    site_id: Optional[str] = Field(None, description="Local site ID")
    store_id: Optional[str] = Field(None, description="Local store ID")
    shopper_id: Optional[str] = Field(None, description="Local shopper ID")
    
    currency: str = Field("GBP", description="Currency")
    items: List[AiFiItem] = Field(..., description="Order items")
    occurred_at: Optional[datetime] = Field(None, description="Order timestamp")
    
    @field_validator('tenant_id', 'site_id', 'store_id', 'shopper_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError('Invalid UUID format')
        return v

class DeviceStatusUpdate(BaseModel):
    """Phase 2: Update device status"""
    status: str = Field(..., description="Device status: online, offline, error, maintenance")
    health_score: Optional[int] = Field(None, description="Health score 0-100", ge=0, le=100)
    details: Optional[Dict[str, Any]] = Field(None, description="Status details")

class DeviceAlertCreate(BaseModel):
    """Phase 2: Create device alert"""
    alert_type: str = Field(..., description="Alert type: offline, error, low_health")
    severity: str = Field("warning", description="Severity: info, warning, critical")
    message: str = Field(..., description="Alert message")

class ReviewResolvePayload(BaseModel):
    """Review resolution payload"""
    mapped_sku: Optional[str] = Field(None, description="Mapped SKU")
    status: str = Field("resolved", description="Resolution status")
    notes: Optional[str] = Field(None, description="Resolution notes")
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in ("resolved", "ignored"):
            raise ValueError("Status must be 'resolved' or 'ignored'")
        return v

class OrderResponse(BaseModel):
    """Order processing response"""
    ok: bool = Field(..., description="Success status")
    order_id: Optional[int] = Field(None, description="Created order ID")
    total_minor: Optional[int] = Field(None, description="Total amount in minor units")
    currency: Optional[str] = Field(None, description="Currency")
    unknown_items: Optional[List[dict]] = Field(None, description="Unknown items requiring review")

# =============================================================================
# UTILITIES
# =============================================================================

def set_rls_context(db: Session, tenant_id: str, user_id: str = None):
    """Set RLS context for database session"""
    try:
        db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.current_user_id = :user_id"), {"user_id": user_id})
    except Exception as e:
        pass  # RLS not configured yet

# =============================================================================
# AUTHENTICATION & AUTHORIZATION
# =============================================================================

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Get user context from JWT or API key"""
    # Try API key first (simplified for CV Gateway)
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
                "permissions": ["cv_gateway.create", "cv_gateway.view", "cv_gateway.admin"]
            }
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Try JWT
    if authorization and "Bearer " in authorization:
        try:
            token = authorization.replace("Bearer ", "")
            claims = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return claims
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid JWT")

    # Demo mode (dev only)
    if ALLOW_DEMO:
        logger.warning("Using demo mode - not for production!")
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or required_permission in permissions

def get_db_with_rls(user_context: Dict[str, Any] = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        set_rls_context(db, user_context["tenant_id"], user_context["user_id"])
        yield db
    finally:
        db.close()

# RabbitMQ Publishing
def publish_to_rabbitmq(event_type: str, event_data: Dict[str, Any], tenant_id: str) -> bool:
    """Publish event directly to RabbitMQ"""
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        message = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        channel.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=message,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info(f"Published {event_type} to RabbitMQ")
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False

# Rate limiting with Redis (production-ready)
rate_limit_store = {}

async def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit using Redis"""
    global rate_limit_store

    if redis_client is None:
        return True  # Allow if Redis not available

    current_time = datetime.now()
    minute_key = current_time.replace(second=0, microsecond=0)

    try:
        # Use Redis pipeline for atomic operations
        pipe = redis_client.pipeline()

        # Clean old entries (older than 1 minute)
        cutoff_time = minute_key - timedelta(minutes=1)
        cutoff_key = cutoff_time.strftime("%Y%m%d%H%M")

        # Get current count
        current_key = f"cv_gateway_rate_limit:{user_id}:{minute_key.strftime('%Y%m%d%H%M')}"
        pipe.incr(current_key)
        pipe.expire(current_key, 60)  # Expire after 60 seconds

        results = pipe.execute()
        current_count = results[-2]  # The INCR result

        if current_count > RATE_LIMIT_REQUESTS_PER_MINUTE:
            return False

        return True

    except Exception as e:
        logger.warning(f"Redis rate limit check failed, allowing request: {e}")
        return True  # Fail open for rate limiting

# Audit logging
def audit_log(db_session, action: str, resource_type: str, resource_id: str, user_context: Dict[str, Any],
              request_data: Dict[str, Any] = None, response_status: int = None, error_message: str = None,
              ip_address: str = None, user_agent: str = None):
    """Create audit log entry"""
    try:
        # Create audit log entry
        from sqlalchemy import text

        db_session.execute(text("""
            INSERT INTO audit_logs (tenant_id, table_name, record_id, operation, new_values, changed_by, ip_address, user_agent)
            VALUES (:tenant_id, :table_name, :record_id, :operation, :new_values, :changed_by, :ip_address, :user_agent)
        """), {
            "tenant_id": user_context["tenant_id"],
            "table_name": resource_type,
            "record_id": resource_id,
            "operation": action,
            "new_values": json.dumps({
                "request_data": request_data,
                "response_status": response_status,
                "error_message": error_message,
                "user_id": user_context.get("user_id"),
                "tenant_id": user_context.get("tenant_id")
            }),
            "changed_by": user_context.get("user_id"),
            "ip_address": ip_address,
            "user_agent": user_agent
        })

        db_session.commit()

    except Exception as e:
        logger.warning(f"Failed to create audit log: {e}")
        # Don't fail the main operation if audit logging fails

async def _map_provider(db: Session, provider: str, entity_type: str, external_id: str) -> Optional[str]:
    """Map external provider ID to local ID"""
    row = db.execute(text("""
        SELECT local_id
          FROM provider_mappings
         WHERE provider=:p AND entity_type=:et AND external_id=:eid
         LIMIT 1
    """), {"p": provider, "et": entity_type, "eid": external_id}).first()
    return row[0] if row else None

async def _update_daily(db: Session, when: datetime, tenant_id: str, site_id: Optional[str], 
                       store_id: Optional[str], meter_code: str, delta: int):
    """Update daily usage aggregates"""
    day = when.date()
    upd = db.execute(text("""
        UPDATE usage_aggregates_daily
           SET value = value + :delta
         WHERE day=:d AND tenant_id=:t
           AND COALESCE(site_id,'')=COALESCE(:s,'')
           AND COALESCE(store_id,'')=COALESCE(:st,'')
           AND meter_code=:m
    """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code}).rowcount
    
    if upd == 0:
        try:
            db.execute(text("""
                INSERT INTO usage_aggregates_daily(day, tenant_id, site_id, store_id, meter_code, value)
                VALUES(:d,:t,:s,:st,:m,:v)
            """), {"d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code, "v": delta})
        except Exception:
            # Race condition - try update again
            db.execute(text("""
                UPDATE usage_aggregates_daily
                   SET value = value + :delta
                 WHERE day=:d AND tenant_id=:t
                   AND COALESCE(site_id,'')=COALESCE(:s,'')
                   AND COALESCE(store_id,'')=COALESCE(:st,'')
                   AND meter_code=:m
            """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code})

async def _approval_cover_and_consume(db: Session, cost_centre_id: str, user_id: str, amount: int) -> bool:
    """Check and consume approval coverage for budget overspend"""
    need = amount
    for scoped in (True, False):
        rows = db.execute(text("""
            SELECT id, remaining_minor FROM approval_requests_new
             WHERE cost_centre_id=:cc AND status='approved'
               AND (:u IS NULL OR (user_scope_id = :u))
               AND (:scoped = TRUE AND user_scope_id IS NOT NULL OR :scoped = FALSE AND user_scope_id IS NULL)
             ORDER BY approved_at DESC NULLS LAST, id DESC
        """), {"cc": cost_centre_id, "u": user_id, "scoped": scoped}).all()
        
        for r in rows:
            if need <= 0: 
                break
            ar_id, rem = int(r[0]), int(r[1] or 0)
            if rem <= 0: 
                continue
            take = min(rem, need)
            db.execute(text("UPDATE approval_requests_new SET remaining_minor = remaining_minor - :take WHERE id=:id"),
                       {"take": take, "id": ar_id})
            need -= take
    return need == 0

async def _review_unknown_item(db: Session, provider: str, tenant_id: str, site_id: str, store_id: str,
                         external_sku: str, name: str, qty: int, price_minor: int, payload_fragment: dict):
    """Record unknown item for review"""
    db.execute(text("""
        INSERT INTO cv_unknown_item_reviews(tenant_id, site_id, store_id, provider,
                                            external_sku, name, qty, price_minor, payload_json, status)
        VALUES(:t,:si,:st,:p,:esk,:n,:q,:pm,:pl,'pending')
    """), {"t": tenant_id, "si": site_id, "st": store_id, "p": provider,
           "esk": external_sku, "n": name, "q": qty, "pm": price_minor,
           "pl": json.dumps(payload_fragment)})

async def _apply_inventory_decrements(db: Session, store_id: str, items: list[dict]):
    """Apply inventory decrements for sold items"""
    for item in items:
        sku = item["sku"]
        qty = int(item["qty"])
        
        # Update inventory_new table
        upd = db.execute(text("UPDATE inventory_new SET qty = qty - :q WHERE store_id=:st AND sku=:s"),
                         {"q": qty, "st": store_id, "s": sku}).rowcount
        if upd == 0:
            db.execute(text("INSERT INTO inventory_new(store_id, sku, qty) VALUES(:st, :s, :q)"),
                       {"st": store_id, "s": sku, "q": -qty})
        
        # Record inventory movement
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason, created_at)
            VALUES(:st, :s, :d, 'cv_sale', NOW())
        """), {"st": store_id, "s": sku, "d": -qty})

async def publish_event(db: Session, event_type: str, event_data: dict, tenant_id: Optional[str] = None):
    """Publish event to outbox for reliable delivery"""
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status="pending"
    )
    db.add(event)
    db.commit()

async def log_audit(db: Session, action: str, resource_type: str, resource_id: Optional[str] = None,
                   details: Optional[dict] = None, user_id: Optional[str] = None, tenant_id: Optional[str] = None):
    """Log audit trail"""
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit)
    db.commit()

# =============================================================================
# SAGA PATTERN IMPLEMENTATION
# =============================================================================

class CvOrderSaga:
    """Saga for CV order processing with compensation"""
    
    def __init__(self, db: Session, order_data: dict):
        self.db = db
        self.order_data = order_data
        self.compensation_steps = []
    
    async def execute(self) -> dict:
        """Execute the saga steps"""
        try:
            # Step 1: Resolve IDs
            cv_saga_steps_total.labels(step="resolve_ids", provider=self.order_data["provider"], status="started").inc()
            resolved_ids = await self._resolve_ids()
            cv_saga_steps_total.labels(step="resolve_ids", provider=self.order_data["provider"], status="success").inc()
            
            # Step 2: Validate items
            validation_result = await self._validate_items(resolved_ids)
            if not validation_result["valid"]:
                # Update metrics for unknown items
                cv_unknown_items_total.labels(
                    provider=self.order_data["provider"],
                    tenant_id=resolved_ids["tenant_id"]
                ).inc(len(validation_result.get("unknown_items", [])))
                return validation_result
            
            # Step 3: Check budgets/approvals
            budget_result = await self._check_budget_approvals(resolved_ids)
            if not budget_result["approved"]:
                return budget_result
            
            # Step 4: Create order
            order_result = await self._create_order(resolved_ids, validation_result["validated_items"])
            
            # Step 5: Update inventory
            await self._update_inventory(resolved_ids, validation_result["validated_items"])
            
            # Step 6: Create ledger entries
            await self._create_ledger_entries(resolved_ids, order_result["total_minor"])
            
            # Step 7: Update budget
            await self._update_budget(resolved_ids, order_result["total_minor"])
            
            # Step 8: Record usage metrics
            await self._record_usage_metrics(resolved_ids)
            
            # Step 9: Create trade invoice
            await self._create_trade_invoice(resolved_ids, order_result)
            
            # Step 10: Send notifications
            await self._send_notifications(resolved_ids, order_result)
            
            # Step 11: Publish events
            await self._publish_events(resolved_ids, order_result)
            
            # Commit transaction
            self.db.commit()
            
            return {
                "ok": True,
                "order_id": order_result["order_id"],
                "total_minor": order_result["total_minor"],
                "currency": self.order_data["currency"]
            }
            
        except Exception as e:
            # Execute compensation steps
            await self._compensate()
            raise e
    
    async def _resolve_ids(self) -> dict:
        """Resolve external IDs to local IDs"""
        provider = self.order_data["provider"]
        
        tenant_id = (self.order_data.get("tenant_id") or 
                    (self.order_data.get("tenant_ext_id") and 
                     await _map_provider(self.db, provider, "tenant", self.order_data["tenant_ext_id"])))
        
        site_id = (self.order_data.get("site_id") or 
                  (self.order_data.get("site_ext_id") and 
                   await _map_provider(self.db, provider, "site", self.order_data["site_ext_id"])))
        
        store_id = (self.order_data.get("store_id") or 
                   (self.order_data.get("store_ext_id") and 
                    await _map_provider(self.db, provider, "store", self.order_data["store_ext_id"])))
        
        shopper_id = (self.order_data.get("shopper_id") or 
                     (self.order_data.get("user_ext_id") and 
                      await _map_provider(self.db, provider, "user", self.order_data["user_ext_id"])))

        if not all([tenant_id, site_id, store_id, shopper_id]):
            raise HTTPException(
                status_code=400,
                detail="Mapping failed (tenant/site/store/user). Provide local IDs or external IDs + provider_mappings."
            )
        
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "store_id": store_id,
            "shopper_id": shopper_id
        }
    
    async def _validate_items(self, resolved_ids: dict) -> dict:
        """Validate items and check for unknowns"""
        unknown_items = []
        validated_items = []
        
        for item in self.order_data["items"]:
            # Check if product exists
            prod = self.db.execute(text("SELECT 1 FROM product_master WHERE sku=:s AND active=TRUE"), 
                                  {"s": item.sku}).first()
            
            # Check if price exists
            price = self.db.execute(text("""
                SELECT unit_minor FROM prices WHERE sku=:s AND currency=:c AND active=TRUE
            """), {"s": item.sku, "c": self.order_data["currency"]}).first()
            
            if not prod or not price:
                unknown_items.append({
                    "sku": item.sku,
                    "name": item.name,
                    "qty": item.qty,
                    "price_minor": item.price_minor
                })
                
                # Record for review
                await _review_unknown_item(
                    self.db, self.order_data["provider"], resolved_ids["tenant_id"],
                    resolved_ids["site_id"], resolved_ids["store_id"],
                    item.sku, item.name, item.qty, item.price_minor,
                    {"sku": item.sku, "name": item.name, "qty": item.qty, "price_minor": item.price_minor}
                )
                continue
            
            validated_items.append({
                "sku": item.sku,
                "qty": int(item.qty),
                "unit_minor": int(price[0])
            })
        
        if unknown_items:
            return {
                "valid": False,
                "status": 202,
                "reason": "reconciliation_required",
                "unknown_count": len(unknown_items),
                "items": unknown_items
            }
        
        return {
            "valid": True,
            "validated_items": validated_items
        }
    
    async def _check_budget_approvals(self, resolved_ids: dict) -> dict:
        """Check budget and approval coverage"""
        # Get shopper cost centre
        cc_row = self.db.execute(text("""
            SELECT cost_centre_id FROM user_cost_centres
             WHERE user_id=:u ORDER BY id ASC LIMIT 1
        """), {"u": resolved_ids["shopper_id"]}).first()
        
        cost_centre_id = cc_row[0] if cc_row else None

        if not cost_centre_id:
            return {"approved": True}  # No budget constraints
        
        # Check budget
        budget = self.db.execute(text("""
            SELECT limit_minor, spent_minor FROM budgets_new
                 WHERE cost_centre_id=:cc ORDER BY budget_id DESC LIMIT 1
            """), {"cc": cost_centre_id}).first()
        
        if budget:
            remaining = int(budget[0]) - int(budget[1])
            total_minor = sum(item["qty"] * item["unit_minor"] for item in self.order_data["items"])
            
            if remaining < total_minor:
                need = total_minor - max(0, remaining)
                if not await _approval_cover_and_consume(self.db, cost_centre_id, resolved_ids["shopper_id"], need):
                    return {
                        "approved": False,
                        "status": 403,
                        "detail": "Budget would overspend (hard block); no approval cover"
                    }
        
        return {"approved": True, "cost_centre_id": cost_centre_id}
    
    async def _create_order(self, resolved_ids: dict, validated_items: list) -> dict:
        """Create order and line items"""
        total_minor = sum(item["qty"] * item["unit_minor"] for item in validated_items)
        
        # Create order
        self.db.execute(text("""
            INSERT INTO orders_new(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                               provider, provider_order_id, total_minor, currency, status, occurred_at)
            VALUES(:t,:si,:st,:u,:cc,:p,:po,:tot,:cur,'completed',:occ)
        """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"], 
               "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"],
               "cc": resolved_ids.get("cost_centre_id"), "p": self.order_data["provider"],
               "po": self.order_data["provider_order_id"], "tot": total_minor,
               "cur": self.order_data["currency"], "occ": self.order_data.get("occurred_at", datetime.now(timezone.utc))})
        
        order_id = self.db.execute(text("SELECT currval(pg_get_serial_sequence('orders_new','order_id'))")).scalar()
        
        # Create order items
        for item in validated_items:
            self.db.execute(text("""
                INSERT INTO order_items_new(order_id, sku, name, qty, price_minor)
                VALUES(:oid,:sku,:name,:qty,:price)
            """), {"oid": order_id, "sku": item["sku"], "name": item["sku"], 
                   "qty": item["qty"], "price": item["unit_minor"]})
        
        # Add compensation step
        self.compensation_steps.append(("delete_order", {"order_id": order_id}))
        
        return {"order_id": order_id, "total_minor": total_minor}
    
    async def _update_inventory(self, resolved_ids: dict, validated_items: list):
        """Update inventory levels"""
        await _apply_inventory_decrements(resolved_ids["store_id"], validated_items)
        
        # Add compensation step
        self.compensation_steps.append(("restore_inventory", {
            "store_id": resolved_ids["store_id"],
            "items": validated_items
        }))
    
    async def _create_ledger_entries(self, resolved_ids: dict, total_minor: int):
        """Create ledger entries"""
        # Debit cost centre spend
        self.db.execute(text("""
            INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:si,:st,'cv_order',:ref,'CV order')
        """), {"t": resolved_ids["tenant_id"], "amt": total_minor, "cur": self.order_data["currency"],
               "cc": resolved_ids.get("cost_centre_id"), "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "ref": str(resolved_ids.get("order_id"))})
        
        # Credit tenant clearing
        self.db.execute(text("""
            INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:si,:st,'cv_order',:ref,'CV order')
        """), {"t": resolved_ids["tenant_id"], "amt": total_minor, "cur": self.order_data["currency"],
               "cc": resolved_ids.get("cost_centre_id"), "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "ref": str(resolved_ids.get("order_id"))})
    
    async def _update_budget(self, resolved_ids: dict, total_minor: int):
        """Update budget spent amount"""
        if resolved_ids.get("cost_centre_id"):
            self.db.execute(text("""
                UPDATE budgets_new SET spent_minor = spent_minor + :amt 
                WHERE cost_centre_id=:cc
            """), {"amt": total_minor, "cc": resolved_ids["cost_centre_id"]})
    
    async def _record_usage_metrics(self, resolved_ids: dict):
        """Record usage metrics"""
        when = self.order_data.get("occurred_at", datetime.now(timezone.utc))
        
        # Record order event
        self.db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:si,:st,'orders',:u,1,:occ)
        """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "occ": when})
        
        await _update_daily(self.db, when, resolved_ids["tenant_id"], resolved_ids["site_id"],
                           resolved_ids["store_id"], "orders", 1)
        
        # Check for unique shoppers
        exist = self.db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:si,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "d": when.date()}).first()
        
        if not exist:
            self.db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:si,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
                   "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "occ": when})
            
            await _update_daily(self.db, when, resolved_ids["tenant_id"], resolved_ids["site_id"],
                               resolved_ids["store_id"], "unique_shoppers", 1)
    
    async def _create_trade_invoice(self, resolved_ids: dict, order_result: dict):
        """Create trade invoice if applicable"""
        create_trade_invoice_if_applicable(
            self.db, resolved_ids["tenant_id"], int(order_result["order_id"]),
            order_result["total_minor"], self.order_data["currency"],
            resolved_ids["site_id"], resolved_ids["store_id"]
        )
    
    async def _send_notifications(self, resolved_ids: dict, order_result: dict):
        """Send order notifications"""
        self.db.execute(text("""
            INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
            VALUES(:t,:u,'dev','CV Order Receipt', :body)
        """), {"t": resolved_ids["tenant_id"], "u": resolved_ids["shopper_id"],
               "body": f"CV Order {order_result['order_id']} total {order_result['total_minor']} {self.order_data['currency']}"})
    
    async def _publish_events(self, resolved_ids: dict, order_result: dict):
        """Publish events for integration"""
        # Publish ORDER_CREATED event
        await publish_event(self.db, "ORDER_CREATED", {
            "order_id": order_result["order_id"],
            "tenant_id": resolved_ids["tenant_id"],
            "provider": self.order_data["provider"],
            "total_minor": order_result["total_minor"],
            "currency": self.order_data["currency"]
        }, resolved_ids["tenant_id"])
    
    async def _compensate(self):
        """Execute compensation steps in reverse order"""
        for step_name, step_data in reversed(self.compensation_steps):
            try:
                if step_name == "delete_order":
                    self.db.execute(text("DELETE FROM order_items_new WHERE order_id=:oid"), 
                                   {"oid": step_data["order_id"]})
                    self.db.execute(text("DELETE FROM orders_new WHERE order_id=:oid"), 
                                   {"oid": step_data["order_id"]})
                
                elif step_name == "restore_inventory":
                    for item in step_data["items"]:
                        self.db.execute(text("""
                            UPDATE inventory_new SET qty = qty + :q WHERE store_id=:st AND sku=:s
                        """), {"q": item["qty"], "st": step_data["store_id"], "s": item["sku"]})
                
            except Exception as e:
                # Log compensation failure but continue
                print(f"Compensation step {step_name} failed: {e}")

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    get_engine()
    init_db()
    yield
    # Shutdown

app = FastAPI(
    title="ZeroQue CV Gateway V4.1",
    version="2.0.0",
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

# Add middleware
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/cv/webhook/order"),
])

# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============================================================================
# HEALTH AND ROOT ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": "2.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# DEVICE MONITORING ENDPOINTS (Phase 2)
# =============================================================================

@app.get("/devices/status")
async def list_devices(
    tenant_id: str = Query(...),
    site_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """
    Phase 2: List all devices with health status
    Filter by tenant, site, and status
    """
    try:
        set_rls_context(db, tenant_id)
        
        # Build query
        query = "SELECT * FROM devices WHERE tenant_id = :tenant_id"
        params = {"tenant_id": tenant_id}
        
        if site_id:
            query += " AND site_id = :site_id"
            params["site_id"] = site_id
        
        if status:
            query += " AND status = :status"
            params["status"] = status
        
        query += " ORDER BY created_at DESC"
        
        result = db.execute(text(query), params)
        devices = result.fetchall()
        
        device_list = []
        for device in devices:
            device_list.append({
                "device_id": device[0],
                "tenant_id": str(device[1]),
                "site_id": str(device[2]) if device[2] else None,
                "device_type": device[3],
                "device_name": device[4],
                "zone": device[5],
                "status": device[6],
                "health_score": device[7],
                "last_heartbeat": device[8].isoformat() if device[8] else None,
                "device_metadata": device[9],
                "created_at": device[10].isoformat() if device[10] else None
            })
        
        logger.info(f"Listed {len(device_list)} devices for tenant {tenant_id}")
        
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "status_filter": status,
            "total_devices": len(device_list),
            "devices": device_list
        }
        
    except Exception as e:
        logger.error(f"Failed to list devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/devices/{device_id}/status")
async def get_device_status(
    device_id: str,
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """Phase 2: Get single device status"""
    try:
        set_rls_context(db, tenant_id)
        
        device = db.execute(
            text("SELECT * FROM devices WHERE device_id = :device_id AND tenant_id = :tenant_id"),
            {"device_id": device_id, "tenant_id": tenant_id}
        ).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        # Get recent status logs
        logs = db.execute(
            text("""
                SELECT status, health_score, details, created_at 
                FROM device_status_logs 
                WHERE device_id = :device_id 
                ORDER BY created_at DESC LIMIT 10
            """),
            {"device_id": device_id}
        ).fetchall()
        
        # Get open alerts
        alerts = db.execute(
            text("""
                SELECT alert_type, severity, message, status, created_at 
                FROM device_alerts 
                WHERE device_id = :device_id AND status = 'open'
                ORDER BY created_at DESC
            """),
            {"device_id": device_id}
        ).fetchall()
        
        return {
            "device_id": device[0],
            "tenant_id": str(device[1]),
            "site_id": str(device[2]) if device[2] else None,
            "device_type": device[3],
            "device_name": device[4],
            "zone": device[5],
            "status": device[6],
            "health_score": device[7],
            "last_heartbeat": device[8].isoformat() if device[8] else None,
            "device_metadata": device[9],
            "recent_logs": [
                {
                    "status": log[0],
                    "health_score": log[1],
                    "details": log[2],
                    "created_at": log[3].isoformat()
                }
                for log in logs
            ],
            "open_alerts": [
                {
                    "alert_type": alert[0],
                    "severity": alert[1],
                    "message": alert[2],
                    "status": alert[3],
                    "created_at": alert[4].isoformat()
                }
                for alert in alerts
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get device status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/devices/{device_id}/status")
async def update_device_status(
    device_id: str,
    status_update: DeviceStatusUpdate,
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """
    Phase 2: Update device status (heartbeat, offline, error)
    Called by devices to report health or by monitoring system
    """
    try:
        set_rls_context(db, tenant_id)
        
        # Check if device exists
        device = db.execute(
            text("SELECT status FROM devices WHERE device_id = :device_id AND tenant_id = :tenant_id"),
            {"device_id": device_id, "tenant_id": tenant_id}
        ).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        old_status = device[0]
        
        # Update device
        db.execute(
            text("""
                UPDATE devices 
                SET status = :status, 
                    health_score = :health_score,
                    last_heartbeat = :heartbeat,
                    updated_at = :now
                WHERE device_id = :device_id AND tenant_id = :tenant_id
            """),
            {
                "status": status_update.status,
                "health_score": status_update.health_score,
                "heartbeat": datetime.now(timezone.utc),
                "now": datetime.now(timezone.utc),
                "device_id": device_id,
                "tenant_id": tenant_id
            }
        )
        
        # Log status change
        db.execute(
            text("""
                INSERT INTO device_status_logs (device_id, tenant_id, status, health_score, details)
                VALUES (:device_id, :tenant_id, :status, :health_score, :details)
            """),
            {
                "device_id": device_id,
                "tenant_id": tenant_id,
                "status": status_update.status,
                "health_score": status_update.health_score,
                "details": json.dumps(status_update.details) if status_update.details else None
            }
        )
        
        # Create alert if status changed to offline or error
        if status_update.status in ["offline", "error"] and old_status not in ["offline", "error"]:
            db.execute(
                text("""
                    INSERT INTO device_alerts (device_id, tenant_id, alert_type, severity, message)
                    VALUES (:device_id, :tenant_id, :alert_type, :severity, :message)
                """),
                {
                    "device_id": device_id,
                    "tenant_id": tenant_id,
                    "alert_type": status_update.status,
                    "severity": "critical" if status_update.status == "error" else "warning",
                    "message": f"Device {device_id} is now {status_update.status}"
                }
            )
            
            # TODO: Publish DEVICE_STATUS event for Entitlements usage tracking
            # TODO: Send webhook to Notifications service for alerting
        
        db.commit()
        
        logger.info(f"Updated device {device_id} status to {status_update.status}")
        
        return {
            "success": True,
            "device_id": device_id,
            "old_status": old_status,
            "new_status": status_update.status,
            "health_score": status_update.health_score,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update device status: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/devices/{device_id}/alert")
async def create_device_alert(
    device_id: str,
    alert: DeviceAlertCreate,
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """Phase 2: Create device alert manually"""
    try:
        set_rls_context(db, tenant_id)
        
        # Create alert
        db.execute(
            text("""
                INSERT INTO device_alerts (device_id, tenant_id, alert_type, severity, message)
                VALUES (:device_id, :tenant_id, :alert_type, :severity, :message)
            """),
            {
                "device_id": device_id,
                "tenant_id": tenant_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message
            }
        )
        
        db.commit()
        
        logger.info(f"Created alert for device {device_id}: {alert.alert_type}")
        
        return {
            "success": True,
            "device_id": device_id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to create device alert: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/cv/webhook/order", response_model=OrderResponse)
async def cv_order_webhook(
    order: AiFiOrder,
    user_context: Dict[str, Any] = Depends(get_user_context),
    db = Depends(get_db_with_rls)
):
    """Process CV order webhook with saga pattern"""
    # Update metrics
    cv_gateway_requests_total.labels(
        method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="started"
    ).inc()
    
    start_time = datetime.now()
    
    try:
        set_rls_context(db, order.tenant_id or order.tenant_ext_id or "default")
        
        # Create and execute saga
        saga = CvOrderSaga(db, order.model_dump())
        result = await saga.execute()
        
        # Log audit
        await log_audit(
            db, "cv_order_processed", "order",
            details={"provider": order.provider, "order_id": result.get("order_id")},
            tenant_id=order.tenant_id
        )
        
        # Update metrics
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="success", reason="completed"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="success"
        ).inc()

        # Audit log
        audit_log(db, "create_cv_order", "cv_orders_new", str(order.order_id), user_context, order.dict(), 201)

        return OrderResponse(**result)
        
    except HTTPException as e:
        # Update metrics for HTTP exceptions
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="failure", reason=f"http_{e.status_code}"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="error"
        ).inc()
        raise
    except Exception as e:
        db.rollback()
        
        # Update metrics for other exceptions
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="failure", reason="exception"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="error"
        ).inc()
        
        raise HTTPException(status_code=500, detail=f"Order processing failed: {str(e)}")

# =============================================================================
# REVIEW MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/cv/reviews")
async def list_reviews(
    tenant_id: str = Query(...),
    status: str = Query("pending"),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    """List unknown item reviews for reconciliation"""
    try:
        set_rls_context(db, tenant_id)
        
        rows = db.execute(text("""
            SELECT id, provider, external_sku, name, qty, price_minor, status, created_at
              FROM cv_unknown_item_reviews
             WHERE tenant_id=:t AND status=:s
             ORDER BY id DESC
             LIMIT :l
        """), {"t": tenant_id, "s": status, "l": limit}).all()
        
        return [{
            "id": str(r[0]), "provider": r[1], "external_sku": r[2], "name": r[3],
            "qty": int(r[4]), "price_minor": int(r[5] or 0), "status": r[6], "created_at": str(r[7])
        } for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list reviews: {str(e)}")

@app.post("/cv/reviews/{review_id}/resolve")
async def resolve_review(
    review_id: str = Path(...),
    payload: ReviewResolvePayload = Body(...),
    db: Session = Depends(get_db)
):
    """Resolve an unknown item review"""
    try:
        # Get review to find tenant_id
        review = db.execute(text("""
            SELECT tenant_id FROM cv_unknown_item_reviews WHERE id=:id
        """), {"id": review_id}).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        
        set_rls_context(db, str(review[0]))
        
        # Update review
        db.execute(text("""
            UPDATE cv_unknown_item_reviews
               SET status=:st, mapped_sku=:ms, notes=:n, resolved_at=NOW()
             WHERE id=:id
        """), {"st": payload.status, "ms": payload.mapped_sku, "n": payload.notes, "id": review_id})
        
        db.commit()
        
        # Log audit
        await log_audit(
            db, "review_resolved", "cv_unknown_item_review",
            details={"review_id": review_id, "status": payload.status},
            tenant_id=str(review[0])
        )
        
        return {"id": review_id, "status": payload.status}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve review: {str(e)}")

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/cv/v4/integration/orders/create-order")
async def create_order_in_orders_service(
    tenant_id: str = Body(...),
    order_data: Dict[str, Any] = Body(...)
):
    """Integration endpoint to create order in Orders service"""
    try:
        logger.info(f"Creating order in Orders service for CV Gateway: tenant_id={tenant_id}")
        
        # Prepare order data for Orders service
        orders_data = {
            "tenant_id": tenant_id,
            "site_id": order_data.get("site_id"),
            "store_id": order_data.get("store_id"),
            "user_id": order_data.get("shopper_id"),
            "currency": order_data.get("currency", "GBP"),
            "total_minor": order_data.get("total_minor", 0),
            "items": order_data.get("items", []),
            "provider": order_data.get("provider"),
            "provider_order_id": order_data.get("provider_order_id"),
            "event_source": "cv_gateway"
        }
        
        # Notify Orders service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://localhost:8081/orders/v2",
                    json=orders_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created order in Orders service: {result}")
                    return {"ok": True, "order_created": True, "order_id": result.get("order_id")}
                else:
                    logger.warning(f"Orders service returned status {response.status_code}")
                    return {"ok": False, "order_created": False, "error": "Orders service error"}
                    
        except Exception as e:
            logger.error(f"Failed to create order in Orders service: {str(e)}")
            return {"ok": False, "order_created": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error creating order in Orders service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

@app.post("/cv/v4/integration/approvals/budget-check")
async def check_budget_with_approvals_service(
    tenant_id: str = Body(...),
    amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    cost_centre_id: str = Body(None),
    site_id: str = Body(None),
    store_id: str = Body(None)
):
    """Integration endpoint to check budget with Approvals service"""
    try:
        logger.info(f"Checking budget with Approvals service: tenant_id={tenant_id}, amount={amount_minor}")
        
        # Prepare budget check data
        budget_check_data = {
            "tenant_id": tenant_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "cost_centre_id": cost_centre_id,
            "site_id": site_id,
            "store_id": store_id
        }
        
        # Notify Approvals service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8084/approvals/v2/integration/cv-gateway/budget-check",
                    json=budget_check_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully checked budget with Approvals service: {result}")
                    return result
                else:
                    logger.warning(f"Approvals service returned status {response.status_code}")
                    return {"ok": False, "error": "Approvals service error"}
                    
        except Exception as e:
            logger.error(f"Failed to check budget with Approvals service: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error checking budget with Approvals service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check budget: {str(e)}")

@app.post("/cv/v4/integration/billing/create-invoice")
async def create_invoice_with_billing_service(
    tenant_id: str = Body(...),
    order_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None),
    items: List[Dict[str, Any]] = Body(...)
):
    """Integration endpoint to create invoice with Billing service"""
    try:
        logger.info(f"Creating invoice with Billing service: tenant_id={tenant_id}, order_id={order_id}")
        
        # Prepare invoice data
        invoice_data = {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "total_amount_minor": total_amount_minor,
            "currency": currency,
            "customer_id": customer_id,
            "items": items
        }
        
        # Notify Billing service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://localhost:8083/billing/v2/integration/cv-gateway/invoice-creation",
                    json=invoice_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created invoice with Billing service: {result}")
                    return result
                else:
                    logger.warning(f"Billing service returned status {response.status_code}")
                    return {"ok": False, "error": "Billing service error"}
                    
        except Exception as e:
            logger.error(f"Failed to create invoice with Billing service: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error creating invoice with Billing service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")

@app.get("/cv/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

# =============================================================================
# STATISTICS ENDPOINTS
# =============================================================================

@app.get("/cv/orders")
async def list_cv_orders(
    tenant_id: str = Query(...),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    """List CV orders for a tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        rows = db.execute(text("""
            SELECT order_id, provider, provider_order_id, total_minor, currency, status, occurred_at
              FROM orders_new
             WHERE tenant_id=:t AND provider IS NOT NULL
             ORDER BY occurred_at DESC
             LIMIT :l
        """), {"t": tenant_id, "l": limit}).all()
        
        return [{
            "order_id": int(r[0]), "provider": r[1], "provider_order_id": r[2],
            "total_minor": int(r[3]), "currency": r[4], "status": r[5], "occurred_at": str(r[6])
        } for r in rows]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CV orders: {str(e)}")

@app.get("/cv/stats/{tenant_id}")
async def get_cv_stats(tenant_id: str = Path(...), db: Session = Depends(get_db)):
    """Get CV statistics for a tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        # Total orders
        total_orders = db.execute(text("""
            SELECT COUNT(*) FROM orders_new WHERE tenant_id=:t AND provider IS NOT NULL
        """), {"t": tenant_id}).scalar()
        
        # Total revenue
        total_revenue = db.execute(text("""
            SELECT COALESCE(SUM(total_minor), 0) FROM orders_new 
            WHERE tenant_id=:t AND provider IS NOT NULL AND status='completed'
        """), {"t": tenant_id}).scalar()
        
        # Pending reviews
        pending_reviews = db.execute(text("""
            SELECT COUNT(*) FROM cv_unknown_item_reviews 
            WHERE tenant_id=:t AND status='pending'
        """), {"t": tenant_id}).scalar()
        
        return {
            "tenant_id": tenant_id,
            "total_orders": int(total_orders),
            "total_revenue_minor": int(total_revenue),
            "pending_reviews": int(pending_reviews)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get CV stats: {str(e)}")

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/cv/aifi/webhook/order")
async def aifi_order_legacy(payload: dict = Body(...)):
    """Legacy AiFi order webhook - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/webhook/order",
        "message": "This endpoint is deprecated. Please use /cv/webhook/order with provider parameter."
    }

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_cv_order(self, tenant_id: str, order_data: Dict[str, Any]):
    """Process CV order asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process order logic here
            logger.info(f"Processing CV order for tenant {tenant_id}")
            
            # Update metrics
            cv_gateway_requests_total.labels(method="POST", endpoint="order", provider="async", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process CV order for tenant {tenant_id}: {e}")
        cv_gateway_requests_total.labels(method="POST", endpoint="order", provider="async", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_cv_session(self, tenant_id: str, session_data: Dict[str, Any]):
    """Process CV session asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process session logic here
            logger.info(f"Processing CV session for tenant {tenant_id}")
            
            # Update metrics
            cv_gateway_requests_total.labels(method="POST", endpoint="session", provider="async", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process CV session for tenant {tenant_id}: {e}")
        cv_gateway_requests_total.labels(method="POST", endpoint="session", provider="async", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_site_created(self, site_id: str, site_data: Dict[str, Any]):
    """
    Phase 2: Process SITE_CREATED events from Provisioning
    Syncs devices from device_metadata to Device registry
    """
    try:
        tenant_id = site_data.get("tenant_id")
        device_metadata = site_data.get("device_metadata", {})
        
        logger.info(f"Processing SITE_CREATED for CV Gateway site: {site_id}, tenant: {tenant_id}")
        
        with SessionLocal() as db:
            if tenant_id:
                set_rls_context(db, tenant_id)
            
            # Sync cameras
            cameras = device_metadata.get("cameras", [])
            for camera in cameras:
                try:
                    db.execute(text("""
                        INSERT INTO devices (device_id, tenant_id, site_id, device_type, device_name, zone, status, device_metadata)
                        VALUES (:device_id, :tenant_id, :site_id, 'camera', :device_name, :zone, 'online', :metadata)
                        ON CONFLICT (device_id) DO UPDATE SET
                            device_name = EXCLUDED.device_name,
                            zone = EXCLUDED.zone,
                            device_metadata = EXCLUDED.device_metadata
                    """), {
                        "device_id": camera.get("id"),
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "device_name": camera.get("id"),
                        "zone": camera.get("zone"),
                        "metadata": json.dumps(camera)
                    })
                except Exception as e:
                    logger.warning(f"Failed to sync camera {camera.get('id')}: {e}")
            
            # Sync sensors
            sensors = device_metadata.get("sensors", [])
            for sensor in sensors:
                try:
                    db.execute(text("""
                        INSERT INTO devices (device_id, tenant_id, site_id, device_type, device_name, zone, status, device_metadata)
                        VALUES (:device_id, :tenant_id, :site_id, 'sensor', :device_name, :zone, 'online', :metadata)
                        ON CONFLICT (device_id) DO UPDATE SET
                            device_name = EXCLUDED.device_name,
                            zone = EXCLUDED.zone,
                            device_metadata = EXCLUDED.device_metadata
                    """), {
                        "device_id": sensor.get("id"),
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "device_name": sensor.get("id"),
                        "zone": sensor.get("zone"),
                        "metadata": json.dumps(sensor)
                    })
                except Exception as e:
                    logger.warning(f"Failed to sync sensor {sensor.get('id')}: {e}")
            
            # Sync entry devices
            entry_devices = device_metadata.get("entry_devices", [])
            for entry_device in entry_devices:
                try:
                    db.execute(text("""
                        INSERT INTO devices (device_id, tenant_id, site_id, device_type, device_name, zone, status, device_metadata)
                        VALUES (:device_id, :tenant_id, :site_id, 'entry_device', :device_name, :zone, 'online', :metadata)
                        ON CONFLICT (device_id) DO UPDATE SET
                            device_name = EXCLUDED.device_name,
                            device_metadata = EXCLUDED.device_metadata
                    """), {
                        "device_id": entry_device.get("id"),
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "device_name": entry_device.get("id"),
                        "zone": None,
                        "metadata": json.dumps(entry_device)
                    })
                except Exception as e:
                    logger.warning(f"Failed to sync entry device {entry_device.get('id')}: {e}")
            
            db.commit()
            
            total_devices = len(cameras) + len(sensors) + len(entry_devices)
            logger.info(f"Synced {total_devices} devices for site {site_id}")
    
    except Exception as e:
        logger.error(f"Failed to process SITE_CREATED for CV Gateway {site_id}: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_cv_gateway_data(self):
    """Clean up old CV gateway data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            
            # Clean up old CV orders
            order_result = db.execute(text("""
                DELETE FROM cv_orders_new 
                WHERE created_at < :cutoff_date AND status IN ('completed', 'cancelled')
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old CV sessions
            session_result = db.execute(text("""
                DELETE FROM cv_sessions_new 
                WHERE created_at < :cutoff_date AND status IN ('completed', 'expired')
            """), {"cutoff_date": cutoff_date})
            
            # Phase 2: Clean up old device status logs
            device_log_result = db.execute(text("""
                DELETE FROM device_status_logs
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            # Phase 2: Clean up resolved device alerts
            alert_result = db.execute(text("""
                DELETE FROM device_alerts
                WHERE status = 'resolved' AND resolved_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {order_result.rowcount} old CV orders, {session_result.rowcount} old CV sessions, {device_log_result.rowcount} device logs, {alert_result.rowcount} resolved alerts")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old CV gateway data: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# EVENT CONSUMPTION WORKERS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_tenant_created(self, tenant_id: str, tenant_data: Dict[str, Any]):
    """Process TENANT_CREATED events for CV Gateway"""
    try:
        logger.info(f"Processing TENANT_CREATED for CV Gateway tenant: {tenant_id}")

        # Create default CV provider mappings for new tenant
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Create default provider mappings
            providers = ["provider_a", "provider_b", "provider_c"]
            for provider in providers:
                # Check if mapping already exists
                existing = db.execute(text("""
                    SELECT 1 FROM provider_mappings
                    WHERE provider = :provider AND tenant_id = :tenant_id
                """), {"provider": provider, "tenant_id": tenant_id}).fetchone()

                if not existing:
                    # Create new provider mapping
                    db.execute(text("""
                        INSERT INTO provider_mappings (provider, entity_type, external_id, local_id, tenant_id)
                        VALUES (:provider, 'provider', :provider, :local_id, :tenant_id)
                    """), {
                        "provider": provider,
                        "local_id": f"{provider}_{tenant_id}",
                        "tenant_id": tenant_id
                    })

            db.commit()
            logger.info(f"Created default provider mappings for CV Gateway tenant: {tenant_id}")

    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED for CV Gateway {tenant_id}: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_order_completed(self, order_id: str, order_data: Dict[str, Any]):
    """Process ORDER_COMPLETED events for CV Gateway"""
    try:
        logger.info(f"Processing ORDER_COMPLETED for CV Gateway order: {order_id}")

        # Check if order needs CV processing
        with SessionLocal() as db:
            tenant_id = order_data.get("tenant_id")

            if tenant_id:
                set_rls_context(db, tenant_id)

            # Check if order has unknown items that need CV processing
            unknown_items = order_data.get("unknown_items", [])
            if unknown_items:
                # Process unknown items through CV providers
                for item in unknown_items:
                    # Create CV unknown item review for unknown item
                    cv_review = CvUnknownItemReview(
                        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                        provider="auto",
                        external_sku=item.get("sku", "unknown"),
                        name=item.get("name", "Unknown Item"),
                        qty=item.get("qty", 1),
                        price_minor=item.get("price_minor", 0),
                        payload_json={"original_order_id": order_id, "unknown_item": item},
                        status="pending"
                    )
                    db.add(cv_review)

                db.commit()
                logger.info(f"Created CV orders for unknown items in order: {order_id}")

    except Exception as e:
        logger.error(f"Failed to process ORDER_COMPLETED for CV Gateway {order_id}: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            result = db.execute(text("""
                DELETE FROM outbox_events
                WHERE status = 'published' AND processed_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} old CV Gateway outbox events")

    except Exception as e:
        logger.error(f"Failed to cleanup old CV Gateway outbox events: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8217")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )