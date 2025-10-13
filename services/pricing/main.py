# services/pricing/main.py - ZeroQue Pricing Service V2
# Production-ready pricing service with Celery, RabbitMQ, and saga patterns

import os
import uuid
import time
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Query, Body, Header, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings
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

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context from JWT or API key"""
    # Try API key first (simplified for demo)
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
                "permissions": ["payments.create", "payments.refund", "payments.adjust", "pricing.create", "pricing.calculate"]
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

import pybreaker

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev"
    REDIS_URL: str = "redis://localhost:6379/0"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672//"
    ENVIRONMENT: str = "development"
    SERVICE_PORT: int = 8226
    ALLOW_DEMO: bool = False

    class Config:
        env_file = ".env"

SETTINGS = Settings()

SERVICE_NAME = "pricing"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = SETTINGS.DATABASE_URL
REDIS_URL = SETTINGS.REDIS_URL
RABBITMQ_URL = SETTINGS.RABBITMQ_URL
ENVIRONMENT = SETTINGS.ENVIRONMENT

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

# Prometheus metrics - clear registry to avoid duplicates
from prometheus_client import REGISTRY
try:
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
except:
    pass

pricing_operations_total = Counter('pricing_operations_total', 'Total pricing operations', ['operation', 'status'])
pricing_request_duration = Histogram('pricing_request_duration_seconds', 'Pricing request duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

# External service URLs
CATALOG_BASE = os.getenv("CATALOG_BASE", "http://localhost:8008")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8003")

# Logging configuration
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

# Note: Prometheus metrics are defined earlier in the file after clearing the registry

# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

class PricebookV2(Base):
    """Pricebook entity for V2 architecture"""
    __tablename__ = "pricebooks_v2"
    
    pricebook_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    currency = Column(String(3), nullable=False, default='GBP')
    is_active = Column(Boolean, nullable=False, default=True)
    custom_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class PriceRuleV2(Base):
    """Price rule entity"""
    __tablename__ = "price_rules_v2"
    
    rule_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pricebook_id = Column(UUID(as_uuid=True), ForeignKey('pricebooks_v2.pricebook_id'), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=True)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    rule_type = Column(String(20), nullable=False)  # fixed, percentage, formula
    rule_value = Column(Numeric(10, 2), nullable=False)
    min_quantity = Column(Integer, nullable=True)
    max_quantity = Column(Integer, nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    custom_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class CalculatedPriceV2(Base):
    """Calculated price cache"""
    __tablename__ = "calculated_prices_v2"
    
    price_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    pricebook_id = Column(UUID(as_uuid=True), nullable=False)
    base_price_minor = Column(Integer, nullable=False)
    calculated_price_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

class OutboxEvent(Base):
    """Outbox pattern for event publishing"""
    __tablename__ = "outbox_events"
    
    event_id = Column(String(50), primary_key=True)
    event_type = Column(String(50), nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    """Audit logging"""
    __tablename__ = "audit_logs"
    
    log_id = Column(String(50), primary_key=True)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    changes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class PricebookRequest(BaseModel):
    """Pricebook creation request"""
    name: str
    description: Optional[str] = None
    currency: str = "GBP"
    metadata: Optional[Dict[str, Any]] = None

class PriceRuleRequest(BaseModel):
    """Price rule creation request"""
    pricebook_id: str
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    rule_type: str  # fixed, percentage, formula
    rule_value: float
    min_quantity: Optional[int] = None
    max_quantity: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

class PriceCalculationRequest(BaseModel):
    """Price calculation request"""
    product_id: str
    variant_id: Optional[str] = None
    pricebook_id: str
    quantity: int = 1
    base_price_minor: int

class PriceCalculationResponse(BaseModel):
    """Price calculation response"""
    product_id: str
    variant_id: Optional[str] = None
    pricebook_id: str
    quantity: int
    base_price_minor: int
    calculated_price_minor: int
    currency: str
    applied_rules: List[Dict[str, Any]] = []

# =============================================================================
# SAGA PATTERN IMPLEMENTATION
# =============================================================================

class PricebookSaga:
    """Saga for pricebook creation with compensation"""
    
    def __init__(self, db):
        self.db = db
        self.pricebook = None
        self.eid = None
    
    async def exec(self, pricebook_id, tenant_id, req, uctx):
        """Execute pricebook creation saga"""
        start = time.time()
        try:
            # Create pricebook
            self.pricebook = PricebookV2(
                pricebook_id=pricebook_id,
                tenant_id=tenant_id,
                name=req.name,
                description=req.description,
                currency=req.currency,
                metadata=req.metadata
            )
            self.db.add(self.pricebook)
            self.db.commit()
            self.db.refresh(self.pricebook)
            
            # Store outbox event
            self.eid = store_outbox(self.db, "PRICEBOOK_CREATED", str(tenant_id), str(pricebook_id), {
                "pricebook_id": str(pricebook_id),
                "name": req.name,
                "currency": req.currency
            })
            
            # Publish event
            publish_outbox_events.delay()
            
            # Audit log
            audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "pricebook", str(pricebook_id), {
                "name": req.name,
                "currency": req.currency
            })
            
            saga_total.labels(type="pricebook", status="ok").inc()
            saga_duration.labels(type="pricebook").observe(time.time() - start)
            
            return {
                "pricebook_id": str(pricebook_id),
                "name": req.name,
                "currency": req.currency,
                "created": True
            }
            
        except Exception as e:
            await self.comp()
            saga_total.labels(type="pricebook", status="fail").inc()
            raise
    
    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            
            if self.pricebook:
                self.db.delete(self.pricebook)
                self.db.commit()
                
        except Exception as e:
            logger.error("Compensation failed", error=str(e))
            self.db.rollback()

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication is handled by the first get_user_context function above

def store_outbox(db, event_type, tenant_id, entity_id, event_data):
    """Store outbox event"""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    outbox_event = OutboxEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=tenant_id,
        event_data=json.dumps(event_data),
        status='pending'
    )
    db.add(outbox_event)
    db.commit()
    return event_id

def audit(db, tenant_id, user_id, action, entity_type, entity_id, changes):
    """Audit logging"""
    try:
        log_id = f"aud_{uuid.uuid4().hex[:12]}"
        audit_log = AuditLog(
            log_id=log_id,
            aggregate_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=json.dumps(changes) if changes else None
        )
        db.add(audit_log)
        db.commit()
    except Exception as e:
        logger.warning("Audit failed", error=str(e))

def set_rls_context(db, tenant_id: str):
    """Set RLS context for database session"""
    try:
        db.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"), {"tenant_id": str(tenant_id)})
    except Exception as e:
        logger.warning(f"RLS context set failed: {e}")

def check_permission(permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or permission in permissions


def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        # Skip RLS in demo mode to avoid transaction issues
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()

    """Best-effort RLS context setter. Tenant-aware DBs may ignore this."""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

def calculate_price(db, product_id, variant_id, pricebook_id, quantity, base_price_minor):
    """Calculate price based on rules"""
    try:
        # Get applicable rules
        rules = db.execute(text("""
            SELECT * FROM price_rules_v2 
            WHERE pricebook_id = :pricebook_id 
            AND (product_id = :product_id OR product_id IS NULL)
            AND (variant_id = :variant_id OR variant_id IS NULL)
            AND is_active = true
            AND (valid_from IS NULL OR valid_from <= NOW())
            AND (valid_until IS NULL OR valid_until >= NOW())
            AND (min_quantity IS NULL OR min_quantity <= :quantity)
            AND (max_quantity IS NULL OR max_quantity >= :quantity)
            ORDER BY product_id DESC, variant_id DESC, created_at DESC
        """), {
            "pricebook_id": pricebook_id,
            "product_id": product_id,
            "variant_id": variant_id,
            "quantity": quantity
        }).fetchall()
        
        calculated_price = base_price_minor
        applied_rules = []
        
        for rule in rules:
            if rule.rule_type == "fixed":
                calculated_price = rule.rule_value * 100  # Convert to minor units
            elif rule.rule_type == "percentage":
                calculated_price = int(calculated_price * (1 + rule.rule_value / 100))
            elif rule.rule_type == "formula":
                # TODO: Implement formula evaluation
                pass
            
            applied_rules.append({
                "rule_id": str(rule.rule_id),
                "rule_type": rule.rule_type,
                "rule_value": float(rule.rule_value),
                "applied_price": calculated_price
            })
        
        return calculated_price, applied_rules
        
    except Exception as e:
        logger.error("Price calculation failed", error=str(e))
        return base_price_minor, []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_external_service(url: str, method: str = "GET", data: Dict = None):
    """Call external service with retry"""
    with httpx.Client() as client:
        if method == "GET":
            response = client.get(url)
        elif method == "POST":
            response = client.post(url, json=data)
        elif method == "PUT":
            response = client.put(url, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        response.raise_for_status()
        return response.json()

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def publish_outbox_events(self):
    """Publish outbox events to RabbitMQ"""
    try:
        with SessionLocal() as db:
            events = db.execute(text("SELECT * FROM outbox_events WHERE status = 'pending' LIMIT 100")).fetchall()
            
            for event in events:
                try:
                    # Publish to RabbitMQ
                    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
                    channel = connection.channel()
                    
                    channel.basic_publish(
                        exchange='pricing_events',
                        routing_key=event.event_type.lower(),
                        body=event.event_data
                    )
                    
                    # Update status
                    db.execute(
                        text("UPDATE outbox_events SET status = 'published', published_at = NOW() WHERE event_id = :id"),
                        {"id": event.event_id}
                    )
                    db.commit()
                    
                    connection.close()
                    
                except Exception as e:
                    logger.error("Failed to publish event", event_id=event.event_id, error=str(e))
                    # Increment retry count
                    db.execute(
                        text("UPDATE outbox_events SET retry_count = retry_count + 1 WHERE event_id = :id"),
                        {"id": event.event_id}
                    )
                    db.commit()
                    
    except Exception as e:
        logger.error("Outbox publishing failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_price_calculation(self, product_id: str, variant_id: str, pricebook_id: str, quantity: int):
    """Process price calculation and cache result"""
    try:
        with SessionLocal() as db:
            # Get base price from catalog service
            catalog_response = call_external_service(f"{CATALOG_BASE}/catalog/products/{product_id}")
            base_price_minor = catalog_response.get("price_minor", 0)
            
            # Calculate price
            calculated_price, applied_rules = calculate_price(
                db, product_id, variant_id, pricebook_id, quantity, base_price_minor
            )
            
            # Cache result
            cached_price = CalculatedPriceV2(
                tenant_id="demo-tenant-id",  # TODO: Get from context
                product_id=product_id,
                variant_id=variant_id,
                pricebook_id=pricebook_id,
                base_price_minor=base_price_minor,
                calculated_price_minor=calculated_price,
                currency="GBP",
                quantity=quantity,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
            )
            db.add(cached_price)
            db.commit()
            
            logger.info("Price calculation processed", 
                       product_id=product_id, 
                       calculated_price=calculated_price)
            
    except Exception as e:
        logger.error("Price calculation failed", 
                    product_id=product_id, 
                    error=str(e))
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_prices(self):
    """Cleanup old calculated prices"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(hours=24)
            result = db.execute(
                text("DELETE FROM calculated_prices_v2 WHERE expires_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            logger.info("Cleaned up old prices", count=result.rowcount)
    except Exception as e:
        logger.error("Price cleanup failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting pricing service", version=SERVICE_VERSION)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down pricing service")

app = FastAPI(
    title="ZeroQue Pricing Service",
    description="Production-ready pricing service with Celery and RabbitMQ",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware
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
# API ENDPOINTS
# =============================================================================


class PriceRuleSaga:
    """Saga for price rule creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.rule = None
        self.eid = None

    async def exec(self, rule_id: str, pricebook_id: str, req: Dict, uctx: Dict):
        """Execute price rule creation saga"""
        start = time.time()
        try:
            # Validate pricebook exists and belongs to tenant
            pricebook = self.db.query(Pricebook).filter(Pricebook.id == pricebook_id).first()
            if not pricebook:
                raise ValueError("Pricebook not found")

            # Check permissions
            if not check_permission(uctx, "pricing.create"):
                raise ValueError("Insufficient permissions")

            # Create price rule
            self.rule = PriceRule(
                id=rule_id,
                pricebook_id=pricebook_id,
                rule_type=req['rule_type'],
                rule_value=req['rule_value'],
                priority=req.get('priority', 0)
            )
            self.db.add(self.rule)
            self.db.commit()
            self.db.refresh(self.rule)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "PRICE_RULE_CREATED", str(pricebook.tenant_id), rule_id, {
                "rule_id": rule_id,
                "pricebook_id": pricebook_id,
                "rule_type": req['rule_type']
            })

            # Publish event
            publish_to_rabbitmq("PRICE_RULE_CREATED", {
                "rule_id": rule_id,
                "pricebook_id": pricebook_id,
                "rule_type": req['rule_type']
            }, str(pricebook.tenant_id))

            saga_total.labels(type="price_rule", status="ok").inc()
            saga_duration.labels(type="price_rule").observe(time.time() - start)
            return {"rule_id": rule_id, "created": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="price_rule", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.rule:
                self.db.delete(self.rule)
                self.db.commit()
        except Exception as e:
            logger.error(f"Price rule compensation failed: {e}")
            self.db.rollback()

class PriceCalculationSaga:
    """Saga for price calculation with compensation"""

    def __init__(self, db):
        self.db = db
        self.calculation = None
        self.eid = None

    async def exec(self, calculation_id: str, tenant_id: str, req: Dict, uctx: Dict):
        """Execute price calculation saga"""
        start = time.time()
        try:
            # Check permissions
            if not check_permission(uctx, "pricing.calculate"):
                raise ValueError("Insufficient permissions")

            # Get product and pricebook
            product = self.db.query(Product).filter(Product.product_id == req['product_id']).first()
            if not product:
                raise ValueError("Product not found")

            pricebook = self.db.query(Pricebook).filter(Pricebook.id == req['pricebook_id']).first()
            if not pricebook:
                raise ValueError("Pricebook not found")

            # Calculate price using pricing rules
            base_price = product.base_price_minor
            final_price = base_price  # Simplified calculation

            # Create price calculation record
            self.calculation = CalculatedPrice(
                id=calculation_id,
                tenant_id=tenant_id,
                product_id=req['product_id'],
                pricebook_id=req['pricebook_id'],
                base_price_minor=base_price,
                final_price_minor=final_price,
                quantity=req['quantity'],
                calculated_at=datetime.now(timezone.utc)
            )
            self.db.add(self.calculation)
            self.db.commit()
            self.db.refresh(self.calculation)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "PRICE_CALCULATED", tenant_id, calculation_id, {
                "calculation_id": calculation_id,
                "product_id": req['product_id'],
                "final_price_minor": final_price
            })

            # Publish event
            publish_to_rabbitmq("PRICE_CALCULATED", {
                "calculation_id": calculation_id,
                "product_id": req['product_id'],
                "final_price_minor": final_price
            }, tenant_id)

            saga_total.labels(type="price_calculation", status="ok").inc()
            saga_duration.labels(type="price_calculation").observe(time.time() - start)
            return {"calculation_id": calculation_id, "final_price_minor": final_price}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="price_calculation", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.calculation:
                self.db.delete(self.calculation)
                self.db.commit()
        except Exception as e:
            logger.error(f"Price calculation compensation failed: {e}")
            self.db.rollback()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/pricebooks")
async def create_pricebook(
    req: PricebookRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new pricebook"""
    start = time.time()
    try:
        pricing_requests_total.labels(endpoint="create_pricebook", status="start").inc()
        
        pricebook_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]
        
        saga = PricebookSaga(db)
        result = await saga.exec(pricebook_id, tenant_id, req, uctx)
        
        pricing_requests_total.labels(endpoint="create_pricebook", status="ok").inc()
        pricing_request_duration.labels(endpoint="create_pricebook").observe(time.time() - start)
        
        return result
        
    except ValueError as e:
        pricing_requests_total.labels(endpoint="create_pricebook", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        pricing_requests_total.labels(endpoint="create_pricebook", status="fail").inc()
        logger.error("Pricebook creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/pricebooks")
async def list_pricebooks(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: SessionLocal = Depends(get_db_with_rls)
):
    """List pricebooks for a tenant"""
    try:
        pricebooks = db.execute(
            text("SELECT * FROM pricebooks_v2 WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        ).fetchall()
        
        return [dict(pricebook._mapping) for pricebook in pricebooks]
        
    except Exception as e:
        logger.error("Failed to list pricebooks", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/pricebooks/{pricebook_id}/rules")
async def create_price_rule(
    pricebook_id: str,
    req: PriceRuleRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a price rule"""
    try:
        rule_id = uuid.uuid4()
        rule = PriceRuleV2(
            rule_id=rule_id,
            pricebook_id=pricebook_id,
            product_id=req.product_id,
            variant_id=req.variant_id,
            rule_type=req.rule_type,
            rule_value=req.rule_value,
            min_quantity=req.min_quantity,
            max_quantity=req.max_quantity,
            valid_from=req.valid_from,
            valid_until=req.valid_until,
            metadata=req.metadata
        )
        db.add(rule)
        db.commit()
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CREATE", "price_rule", str(rule_id), req.dict())
        
        return {"rule_id": str(rule_id), "created": True}
        
    except Exception as e:
        logger.error("Failed to create price rule", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/calculate")
async def calculate_price_endpoint(
    req: PriceCalculationRequest,
    db: SessionLocal = Depends(get_db_with_rls)
):
    """Calculate price for a product"""
    try:
        # Check cache first
        cached = db.execute(text("""
            SELECT * FROM calculated_prices_v2 
            WHERE product_id = :product_id 
            AND (variant_id = :variant_id OR variant_id IS NULL)
            AND pricebook_id = :pricebook_id 
            AND quantity = :quantity
            AND expires_at > NOW()
            ORDER BY calculated_at DESC LIMIT 1
        """), {
            "product_id": req.product_id,
            "variant_id": req.variant_id,
            "pricebook_id": req.pricebook_id,
            "quantity": req.quantity
        }).fetchone()
        
        if cached:
            return PriceCalculationResponse(
                product_id=req.product_id,
                variant_id=req.variant_id,
                pricebook_id=req.pricebook_id,
                quantity=req.quantity,
                base_price_minor=req.base_price_minor,
                calculated_price_minor=cached.calculated_price_minor,
                currency="GBP",
                applied_rules=[]
            )
        
        # Calculate price
        calculated_price, applied_rules = calculate_price(
            db, req.product_id, req.variant_id, req.pricebook_id, req.quantity, req.base_price_minor
        )
        
        return PriceCalculationResponse(
            product_id=req.product_id,
            variant_id=req.variant_id,
            pricebook_id=req.pricebook_id,
            quantity=req.quantity,
            base_price_minor=req.base_price_minor,
            calculated_price_minor=calculated_price,
            currency="GBP",
            applied_rules=applied_rules
        )
        
    except Exception as e:
        logger.error("Price calculation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_price_calculation(self, tenant_id: str, calculation_data: Dict[str, Any]):
    """Process price calculation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process price calculation logic here
            logger.info(f"Processing price calculation for tenant {tenant_id}")
            
            # Update metrics
            pricing_operations_total.labels(operation="calculation", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process price calculation for tenant {tenant_id}: {e}")
        pricing_operations_total.labels(operation="calculation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_pricebook_update(self, tenant_id: str, pricebook_id: str, update_data: Dict[str, Any]):
    """Process pricebook update asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process pricebook update logic here
            logger.info(f"Processing pricebook update for tenant {tenant_id}, pricebook {pricebook_id}")
            
            # Update metrics
            pricing_operations_total.labels(operation="pricebook_update", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process pricebook update: {e}")
        pricing_operations_total.labels(operation="pricebook_update", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_pricing_data(self):
    """Clean up old pricing data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            
            # Clean up old calculated prices
            price_result = db.execute(text("""
                DELETE FROM calculated_prices_v2 
                WHERE calculated_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old price rules
            rule_result = db.execute(text("""
                DELETE FROM price_rules_v2 
                WHERE created_at < :cutoff_date AND is_active = false
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {price_result.rowcount} old calculated prices and {rule_result.rowcount} old price rules")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old pricing data: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================


# =============================================================================
# CELERY WORKERS - Event Consumption
# =============================================================================

@celery_app.task(bind=True, max_retries=3, name='pricing.process_product_created')
def process_product_created(self, event_data: Dict[str, Any]):
    """Process PRODUCT_CREATED event from catalog service"""
    try:
        tenant_id = event_data.get('tenant_id')
        product_id = event_data.get('product_id')
        product_name = event_data.get('name')

        if not all([tenant_id, product_id]):
            logger.error('Missing required fields in PRODUCT_CREATED event')
            return {'status': 'error', 'message': 'Missing required fields'}

        with SessionLocal() as db:
            # Create default pricebook for new product if none exists
            existing_pricebook = db.query(Pricebook).filter(
                Pricebook.tenant_id == tenant_id,
                Pricebook.name == 'Default Pricebook'
            ).first()

            if not existing_pricebook:
                # Create default pricebook
                pricebook_id = f"pb_{uuid.uuid4().hex[:12]}"
                pricebook = Pricebook(
                    id=pricebook_id,
                    tenant_id=tenant_id,
                    name='Default Pricebook',
                    currency='GBP',
                    active=True
                )
                db.add(pricebook)
                db.commit()

                logger.info(f"Created default pricebook {pricebook_id} for tenant {tenant_id}")

        return {'status': 'ok', 'pricebook_created': existing_pricebook is None}

    except Exception as e:
        logger.error(f"Failed to process PRODUCT_CREATED event: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='pricing.cleanup_old_outbox_events')
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
            logger.info(f'Cleaned up {result.rowcount} old outbox events')
            return {'deleted': result.rowcount}

    except Exception as e:
        logger.error(f"Failed to cleanup outbox events: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='pricing.cleanup_old_pricing_data')
def cleanup_old_pricing_data(self):
    """Clean up old pricing data"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            
            # Clean old price calculations
            calc_result = db.execute(
                text("DELETE FROM calculated_prices_v2 WHERE calculated_at < :cutoff"),
                {'cutoff': cutoff}
            )
            
            # Clean old price rules (if not referenced)
            rules_result = db.execute(
                text("DELETE FROM price_rules_v2 WHERE created_at < :cutoff AND id NOT IN (SELECT DISTINCT rule_id FROM plan_rules WHERE rule_id IS NOT NULL)"),
                {'cutoff': cutoff}
            )
            
            db.commit()
            logger.info(f"Cleaned {calc_result.rowcount} old calculations and {rules_result.rowcount} old rules")
            return {'calculations_deleted': calc_result.rowcount, 'rules_deleted': rules_result.rowcount}

    except Exception as e:
        logger.error(f"Failed to cleanup old pricing data: {e}")
        raise self.retry(exc=e, countdown=300)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8226")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )