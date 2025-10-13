# services/catalog/main.py - ZeroQue Catalog Service V2
# Production-ready catalog service with Celery, RabbitMQ, and saga patterns

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
import jwt
import secrets
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Header, HTTPException, Depends

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "catalog"
SERVICE_VERSION = "2.0.0"

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "false").lower() == "true"

# Security scheme
security = HTTPBearer(auto_error=False)


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

# External service URLs
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8007")
INVENTORY_BASE = os.getenv("INVENTORY_BASE", "http://localhost:8008")

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

# Prometheus metrics
catalog_requests_total = Counter('catalog_requests_total', 'Total catalog requests', ['endpoint', 'status'])
catalog_request_duration = Histogram('catalog_request_duration_seconds', 'Catalog request duration', ['endpoint'])
catalog_operations_total = Counter('catalog_operations_total', 'Total catalog operations', ['operation', 'status'])
catalog_duration = Histogram('catalog_duration_seconds', 'Catalog operation duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

class ProductV2(Base):
    """Product entity for V2 architecture"""
    __tablename__ = "products_v2"
    
    product_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    sku = Column(String(100), nullable=False)
    category_id = Column(UUID(as_uuid=True), nullable=True)
    brand = Column(String(100), nullable=True)
    base_price_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    weight_grams = Column(Integer, nullable=True)
    dimensions_cm = Column(JSON, nullable=True)  # {"length": 10, "width": 5, "height": 3}
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ProductVariantV2(Base):
    """Product variant entity"""
    __tablename__ = "product_variants_v2"
    
    variant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey('products_v2.product_id'), nullable=False)
    name = Column(String(200), nullable=False)
    sku = Column(String(100), nullable=False)
    price_adjustment_minor = Column(Integer, nullable=False, default=0)
    attributes = Column(JSON, nullable=True)  # {"color": "red", "size": "L"}
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class CategoryV2(Base):
    """Product category entity"""
    __tablename__ = "categories_v2"
    
    category_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    parent_category_id = Column(UUID(as_uuid=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

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

class ProductRequest(BaseModel):
    """Product creation request"""
    vendor_id: str
    name: str
    description: Optional[str] = None
    sku: str
    category_id: Optional[str] = None
    brand: Optional[str] = None
    base_price_minor: int = 0
    currency: str = "GBP"
    weight_grams: Optional[int] = None
    dimensions_cm: Optional[Dict[str, float]] = None
    metadata: Optional[Dict[str, Any]] = None

class ProductVariantRequest(BaseModel):
    """Product variant creation request"""
    product_id: str
    name: str
    sku: str
    price_adjustment_minor: int = 0
    attributes: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

class CategoryRequest(BaseModel):
    """Category creation request"""
    name: str
    description: Optional[str] = None
    parent_category_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ProductSearchRequest(BaseModel):
    """Product search request"""
    query: Optional[str] = None
    category_id: Optional[str] = None
    vendor_id: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    limit: int = 50
    offset: int = 0

# =============================================================================
# SAGA PATTERN IMPLEMENTATION
# =============================================================================

class ProductSaga:
    """Saga for product creation with compensation"""
    
    def __init__(self, db):
        self.db = db
        self.product = None
        self.eid = None
    
    async def exec(self, product_id, tenant_id, req, uctx):
        """Execute product creation saga"""
        start = time.time()
        try:
            # Create product
            self.product = ProductV2(
                product_id=product_id,
                tenant_id=tenant_id,
                vendor_id=req.vendor_id,
                name=req.name,
                description=req.description,
                sku=req.sku,
                category_id=req.category_id,
                brand=req.brand,
                base_price_minor=req.base_price_minor,
                currency=req.currency,
                weight_grams=req.weight_grams,
                dimensions_cm=req.dimensions_cm,
                metadata=req.metadata
            )
            self.db.add(self.product)
            self.db.commit()
            self.db.refresh(self.product)
            
            # Store outbox event
            self.eid = store_outbox(self.db, "PRODUCT_CREATED", str(tenant_id), str(product_id), {
                "product_id": str(product_id),
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id
            })
            
            # Publish event
            publish_outbox_events.delay()
            
            # Audit log
            audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "product", str(product_id), {
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id
            })
            
            saga_total.labels(type="product", status="ok").inc()
            saga_duration.labels(type="product").observe(time.time() - start)
            
            return {
                "product_id": str(product_id),
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id,
                "created": True
            }
            
        except Exception as e:
            await self.comp()
            saga_total.labels(type="product", status="fail").inc()
            raise
    
    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            
            if self.product:
                self.db.delete(self.product)
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

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context from JWT or API key"""
    # Try API key first (simplified for catalog service)
    if x_api_key:
        # For now, accept any API key in demo mode or validate against known keys
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
                "permissions": ["catalog.create", "catalog.view", "catalog.admin"]
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

def check_permission(user_context: Dict, permission: str) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or permission in permissions

def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set RLS context for database session"""
    try:
        db.rollback()  # Ensure clean state
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
        # Skip RLS in demo mode to avoid transaction issues
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context for authentication"""
    # Demo mode for development
    if os.getenv("ALLOW_DEMO", "false").lower() == "true":
        return {
            "tenant_id": "demo-tenant-id",
            "user_id": "demo-user-id",
            "roles": ["admin"]
        }
    
    # TODO: Implement proper JWT/API key validation
    raise HTTPException(status_code=401, detail="Authentication required")

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
    """Best-effort RLS context setter for tenant scoping."""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

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

@celery_app.task(bind=True, max_retries=3, name='catalog.publish_outbox_events')
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
                        exchange='catalog_events',
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
def process_search_indexing(self, product_id: str):
    """Process search indexing for a product"""
    try:
        with SessionLocal() as db:
            product = db.execute(
                text("SELECT * FROM products_v2 WHERE product_id = :id"),
                {"id": product_id}
            ).fetchone()
            
            if not product:
                raise ValueError("Product not found")
            
            # TODO: Index product in search engine (Elasticsearch, etc.)
            logger.info("Product indexed for search", product_id=product_id)
            
    except Exception as e:
        logger.error("Search indexing failed", product_id=product_id, error=str(e))
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_products(self):
    """Cleanup old inactive products"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            result = db.execute(
                text("DELETE FROM products_v2 WHERE is_active = false AND updated_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            logger.info("Cleaned up old products", count=result.rowcount)
    except Exception as e:
        logger.error("Product cleanup failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting catalog service", version=SERVICE_VERSION)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down catalog service")

app = FastAPI(
    title="ZeroQue Catalog Service",
    description="Production-ready catalog service with Celery and RabbitMQ",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
        CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://yourdomain.com"],  # Restrict origins
    allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# =============================================================================

class VariantSaga:
    """Saga for product variant creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.variant = None
        self.eid = None

    async def exec(self, variant_id, product_id, req, uctx):
        """Execute variant creation saga"""
        start = time.time()
        try:
            # Validate product exists
            product = self.db.query(ProductV2).filter(ProductV2.product_id == product_id).first()
            if not product:
                raise ValueError("Product not found")

            # Check permissions
            if not check_permission(uctx, "catalog.create"):
                raise ValueError("Insufficient permissions")

            # Create variant
            self.variant = ProductVariantV2(
                variant_id=variant_id,
                product_id=product_id,
                name=req.name,
                sku=req.sku,
                price_adjustment_minor=req.price_adjustment_minor,
                attributes=req.attributes,
                is_active=True
            )
            self.db.add(self.variant)
            self.db.commit()
            self.db.refresh(self.variant)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "VARIANT_CREATED", str(product.tenant_id), str(variant_id), {
                "variant_id": str(variant_id),
                "product_id": str(product_id),
                "name": req.name
            })

            # Publish event
            publish_to_rabbitmq("VARIANT_CREATED", {
                "variant_id": str(variant_id),
                "product_id": str(product_id),
                "name": req.name
            }, str(product.tenant_id))

            saga_total.labels(type="variant", status="ok").inc()
            saga_duration.labels(type="variant").observe(time.time() - start)
            return {"variant_id": str(variant_id), "name": req.name, "created": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="variant", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.variant:
                self.db.delete(self.variant)
                self.db.commit()
        except Exception as e:
            logger.error(f"Variant compensation failed: {e}")
            self.db.rollback()

class CategorySaga:
    """Saga for category creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.category = None
        self.eid = None

    async def exec(self, category_id, tenant_id, req, uctx):
        """Execute category creation saga"""
        start = time.time()
        try:
            # Check permissions
            if not check_permission(uctx, "catalog.create"):
                raise ValueError("Insufficient permissions")

            # Check if category name already exists
            existing = self.db.query(CategoryV2).filter(
                CategoryV2.tenant_id == tenant_id,
                CategoryV2.name == req.name
            ).first()
            if existing:
                raise ValueError("Category name already exists")

            # Create category
            self.category = CategoryV2(
                category_id=category_id,
                tenant_id=tenant_id,
                name=req.name,
                description=req.description,
                is_active=True
            )
            self.db.add(self.category)
            self.db.commit()
            self.db.refresh(self.category)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "CATEGORY_CREATED", str(tenant_id), str(category_id), {
                "category_id": str(category_id),
                "name": req.name
            })

            # Publish event
            publish_to_rabbitmq("CATEGORY_CREATED", {
                "category_id": str(category_id),
                "name": req.name
            }, str(tenant_id))

            saga_total.labels(type="category", status="ok").inc()
            saga_duration.labels(type="category").observe(time.time() - start)
            return {"category_id": str(category_id), "name": req.name, "created": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="category", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.category:
                self.db.delete(self.category)
                self.db.commit()
        except Exception as e:
            logger.error(f"Category compensation failed: {e}")
            self.db.rollback()


# API ENDPOINTS
# =============================================================================

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

@app.post("/products")
async def create_product(
    req: ProductRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new product"""
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_product", status="start").inc()
        
        product_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]
        
        saga = ProductSaga(db)
        result = await saga.exec(product_id, tenant_id, req, uctx)
        
        catalog_requests_total.labels(endpoint="create_product", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_product").observe(time.time() - start)
        
        return result
        
    except ValueError as e:
        catalog_requests_total.labels(endpoint="create_product", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        catalog_requests_total.labels(endpoint="create_product", status="fail").inc()
        logger.error("Product creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/products")
async def list_products(
    tenant_id: str = Query(...),
    vendor_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: SessionLocal = Depends(get_db_with_rls)
):
    """List products for a tenant"""
    try:
        query = "SELECT * FROM products_v2 WHERE tenant_id = :tenant_id"
        params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        
        if vendor_id:
            query += " AND vendor_id = :vendor_id"
            params["vendor_id"] = vendor_id
        
        if category_id:
            query += " AND category_id = :category_id"
            params["category_id"] = category_id
        
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        
        products = db.execute(text(query), params).fetchall()
        
        return [dict(product._mapping) for product in products]
        
    except Exception as e:
        logger.error("Failed to list products", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/products/{product_id}")
async def get_product(
    product_id: str,
    db: SessionLocal = Depends(get_db_with_rls)
):
    """Get product by ID"""
    try:
        product = db.execute(
            text("SELECT * FROM products_v2 WHERE product_id = :id"),
            {"id": product_id}
        ).fetchone()
        
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        return dict(product._mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get product", product_id=product_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/products/{product_id}/variants")
async def create_product_variant(
    product_id: str,
    req: ProductVariantRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a product variant using saga pattern"""
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_variant", status="start").inc()
        variant_id = uuid.uuid4()
        saga = VariantSaga(db)
        res = await saga.exec(variant_id, product_id, req, uctx)
        catalog_requests_total.labels(endpoint="create_variant", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_variant").observe(time.time() - start)
        return res
    except ValueError as e:
        catalog_requests_total.labels(endpoint="create_variant", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        catalog_requests_total.labels(endpoint="create_variant", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CREATE", "product_variant", str(variant_id), req.dict())
        
        return {"variant_id": str(variant_id), "created": True}
        
    except Exception as e:
        logger.error("Failed to create product variant", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/categories")
async def create_category(
    req: CategoryRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new category using saga pattern"""
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_category", status="start").inc()
        category_id = uuid.uuid4()
        saga = CategorySaga(db)
        res = await saga.exec(category_id, uctx["tenant_id"], req, uctx)
        catalog_requests_total.labels(endpoint="create_category", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_category").observe(time.time() - start)
        return res
    except ValueError as e:
        catalog_requests_total.labels(endpoint="create_category", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        catalog_requests_total.labels(endpoint="create_category", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))
        
        return {"category_id": str(category_id), "created": True}
        
    except Exception as e:
        logger.error("Failed to create category", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/search")
async def search_products(
    req: ProductSearchRequest,
    db: SessionLocal = Depends(get_db_with_rls)
):
    """Search products"""
    try:
        query = "SELECT * FROM products_v2 WHERE 1=1"
        params = {"limit": req.limit, "offset": req.offset}
        
        if req.query:
            query += " AND (name ILIKE :query OR description ILIKE :query OR sku ILIKE :query)"
            params["query"] = f"%{req.query}%"
        
        if req.category_id:
            query += " AND category_id = :category_id"
            params["category_id"] = req.category_id
        
        if req.vendor_id:
            query += " AND vendor_id = :vendor_id"
            params["vendor_id"] = req.vendor_id
        
        if req.min_price:
            query += " AND base_price_minor >= :min_price"
            params["min_price"] = req.min_price
        
        if req.max_price:
            query += " AND base_price_minor <= :max_price"
            params["max_price"] = req.max_price
        
        query += " AND is_active = true ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        
        products = db.execute(text(query), params).fetchall()
        
        return [dict(product._mapping) for product in products]
        
    except Exception as e:
        logger.error("Product search failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_product_import(self, tenant_id: str, import_data: Dict[str, Any]):
    """Process product import asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process import logic here
            logger.info(f"Processing product import for tenant {tenant_id}")
            
            # Update metrics
            catalog_operations_total.labels(operation="import", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process product import for tenant {tenant_id}: {e}")
        catalog_operations_total.labels(operation="import", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def rebuild_search_index(self, tenant_id: str):
    """Rebuild search index for products"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Rebuild index logic here
            logger.info(f"Rebuilding search index for tenant {tenant_id}")
            
            # Update metrics
            catalog_operations_total.labels(operation="index_rebuild", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to rebuild search index for tenant {tenant_id}: {e}")
        catalog_operations_total.labels(operation="index_rebuild", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_catalog_data(self):
    """Clean up old catalog data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            
            # Clean up old products
            product_result = db.execute(text("""
                DELETE FROM products_v2 
                WHERE created_at < :cutoff_date AND is_active = false
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old categories
            category_result = db.execute(text("""
                DELETE FROM categories_v2 
                WHERE created_at < :cutoff_date AND is_active = false
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {product_result.rowcount} old products and {category_result.rowcount} old categories")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old catalog data: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================


# =============================================================================
# CELERY WORKERS - Event Consumption
# =============================================================================

@celery_app.task(bind=True, max_retries=3, name='catalog.process_tenant_created')
def process_tenant_created(self, event_data: Dict[str, Any]):
    """Process TENANT_CREATED event from provisioning service"""
    try:
        tenant_id = event_data.get('tenant_id')
        tenant_name = event_data.get('name')

        if not tenant_id:
            logger.error('Missing tenant_id in TENANT_CREATED event')
            return {'status': 'error', 'message': 'Missing tenant_id'}

        with SessionLocal() as db:
            # Create default categories for new tenant
            default_categories = [
                {'name': 'Electronics', 'description': 'Electronic devices and accessories'},
                {'name': 'Clothing', 'description': 'Apparel and fashion items'},
                {'name': 'Home & Garden', 'description': 'Home improvement and garden supplies'},
                {'name': 'Sports & Outdoors', 'description': 'Sports equipment and outdoor gear'},
            ]

            created_count = 0
            for cat_data in default_categories:
                try:
                    category = CategoryV2(
                        category_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        name=cat_data['name'],
                        description=cat_data['description'],
                        is_active=True
                    )
                    db.add(category)
                    created_count += 1
                except Exception as e:
                    logger.error(f'Failed to create category {cat_data["name"]}: {e}')

            db.commit()
            logger.info(f'Created {created_count} default categories for tenant {tenant_id}')

        return {'status': 'ok', 'categories_created': created_count}

    except Exception as e:
        logger.error(f'Failed to process TENANT_CREATED event: {e}')
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='catalog.process_vendor_created')
def process_vendor_created(self, event_data: Dict[str, Any]):
    """Process VENDOR_CREATED event"""
    try:
        tenant_id = event_data.get('tenant_id')
        vendor_id = event_data.get('vendor_id')

        if not tenant_id or not vendor_id:
            logger.error('Missing tenant_id or vendor_id in VENDOR_CREATED event')
            return {'status': 'error', 'message': 'Missing required fields'}

        logger.info(f'Processing VENDOR_CREATED for tenant {tenant_id}, vendor {vendor_id}')
        # For now, just log the event - can be extended to create vendor-specific categories
        return {'status': 'ok', 'message': 'Vendor creation processed'}

    except Exception as e:
        logger.error(f'Failed to process VENDOR_CREATED event: {e}')
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='catalog.cleanup_old_outbox_events')
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
        logger.error(f'Failed to cleanup outbox events: {e}')
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='catalog.cleanup_old_audit_logs')
def cleanup_audit_logs(self):
    """Clean up old audit logs"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM audit_logs WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f'Cleaned up {result.rowcount} old audit logs')
            return {'deleted': result.rowcount}

    except Exception as e:
        logger.error(f'Failed to cleanup audit logs: {e}')
        raise self.retry(exc=e, countdown=300)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8215")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )