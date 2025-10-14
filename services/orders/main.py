# services/orders/main.py - ZeroQue Orders Service V2
# Production-ready orders service with Celery, RabbitMQ, and saga patterns

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

SERVICE_NAME = "orders"
SERVICE_VERSION = "4.1.0"

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

# Prometheus metrics
orders_operations_total = Counter('orders_operations_total', 'Total orders operations', ['operation', 'status'])
orders_request_duration = Histogram('orders_request_duration_seconds', 'Orders request duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

# External service URLs
PAYMENTS_BASE = os.getenv("PAYMENTS_BASE", "http://localhost:8005")
BILLING_BASE = os.getenv("BILLING_BASE", "http://localhost:8002")
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
orders_requests_total = Counter('orders_requests_total', 'Total orders requests', ['endpoint', 'status'])
orders_request_duration = Histogram('orders_request_duration_seconds', 'Orders request duration', ['endpoint'])
orders_total = Counter('orders_total', 'Total orders', ['status'])
orders_duration = Histogram('orders_duration_seconds', 'Order processing duration', ['status'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

class OrderV2(Base):
    """Order entity for V2 architecture"""
    __tablename__ = "orders_v2"
    
    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    order_number = Column(String(50), nullable=False, unique=True)
    order_status = Column(String(20), nullable=False, default='pending')
    order_type = Column(String(20), nullable=False, default='purchase')
    total_amount_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    payment_status = Column(String(20), nullable=False, default='pending')
    fulfillment_status = Column(String(20), nullable=False, default='pending')
    shipping_address = Column(JSON, nullable=True)
    billing_address = Column(JSON, nullable=True)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OrderItemV2(Base):
    """Order item entity"""
    __tablename__ = "order_items_v2"
    
    item_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey('orders_v2.order_id'), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    total_price_minor = Column(Integer, nullable=False)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

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

class OrderRequest(BaseModel):
    """Order creation request"""
    customer_id: str
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    order_type: str = "purchase"
    items: List[Dict[str, Any]]
    shipping_address: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

class OrderItemRequest(BaseModel):
    """Order item request"""
    product_id: str
    variant_id: Optional[str] = None
    quantity: int
    unit_price_minor: int

class OrderUpdateRequest(BaseModel):
    """Order update request"""
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

# =============================================================================
# SAGA PATTERN IMPLEMENTATION
# =============================================================================

class OrderSaga:
    """Saga for order creation with compensation"""
    
    def __init__(self, db):
        self.db = db
        self.order = None
        self.order_items = []
        self.eid = None
    
    async def exec(self, order_id, tenant_id, req, uctx):
        """Execute order creation saga"""
        start = time.time()
        try:
            # Create order
            self.order = OrderV2(
                order_id=order_id,
                tenant_id=tenant_id,
                site_id=req.site_id,
                store_id=req.store_id,
                customer_id=req.customer_id,
                order_number=f"ORD-{int(time.time())}",
                order_type=req.order_type,
                shipping_address=req.shipping_address,
                billing_address=req.billing_address,
                metadata=req.metadata
            )
            self.db.add(self.order)
            
            # Calculate total amount
            total_amount = 0
            for item_data in req.items:
                item = OrderItemV2(
                    order_id=order_id,
                    product_id=item_data['product_id'],
                    variant_id=item_data.get('variant_id'),
                    quantity=item_data['quantity'],
                    unit_price_minor=item_data['unit_price_minor'],
                    total_price_minor=item_data['quantity'] * item_data['unit_price_minor']
                )
                self.order_items.append(item)
                self.db.add(item)
                total_amount += item.total_price_minor
            
            self.order.total_amount_minor = total_amount
            self.db.commit()
            self.db.refresh(self.order)
            
            # Store outbox event
            self.eid = store_outbox(self.db, "ORDER_CREATED", str(tenant_id), str(order_id), {
                "order_id": str(order_id),
                "customer_id": req.customer_id,
                "total_amount_minor": total_amount
            })
            
            # Publish event
            publish_outbox_events.delay()
            
            # Audit log
            audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "order", str(order_id), {
                "order_number": self.order.order_number,
                "total_amount_minor": total_amount
            })
            
            saga_total.labels(type="order", status="ok").inc()
            saga_duration.labels(type="order").observe(time.time() - start)
            
            return {
                "order_id": str(order_id),
                "order_number": self.order.order_number,
                "total_amount_minor": total_amount,
                "created": True
            }
            
        except Exception as e:
            await self.comp()
            saga_total.labels(type="order", status="fail").inc()
            raise
    
    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            
            if self.order:
                self.db.delete(self.order)
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

def get_user_context(authorization: Optional[str] = None, x_api_key: Optional[str] = None):
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

@celery_app.task(bind=True, max_retries=3, name='orders.publish_outbox_events')
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
                        exchange='orders_events',
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
def process_order_fulfillment(self, order_id: str):
    """Process order fulfillment"""
    try:
        with SessionLocal() as db:
            order = db.execute(text("SELECT * FROM orders_v2 WHERE order_id = :id"), {"id": order_id}).fetchone()
            if not order:
                raise ValueError("Order not found")
            
            # Call inventory service
            inventory_response = call_external_service(f"{INVENTORY_BASE}/inventory/reserve", "POST", {
                "order_id": order_id,
                "items": []  # TODO: Get order items
            })
            
            # Update order status
            db.execute(
                text("UPDATE orders_v2 SET fulfillment_status = 'fulfilled' WHERE order_id = :id"),
                {"id": order_id}
            )
            db.commit()
            
            logger.info("Order fulfillment processed", order_id=order_id)
            
    except Exception as e:
        logger.error("Order fulfillment failed", order_id=order_id, error=str(e))
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_orders(self):
    """Cleanup old orders"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM orders_v2 WHERE created_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            logger.info("Cleaned up old orders", count=result.rowcount)
    except Exception as e:
        logger.error("Order cleanup failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting orders service", version=SERVICE_VERSION)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down orders service")

app = FastAPI(
    title="ZeroQue Orders Service",
    description="Production-ready orders service with Celery and RabbitMQ",
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

@app.post("/orders")
async def create_order(
    req: OrderRequest,
    db: SessionLocal = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new order"""
    start = time.time()
    try:
        orders_requests_total.labels(endpoint="create_order", status="start").inc()
        
        order_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]
        
        saga = OrderSaga(db)
        result = await saga.exec(order_id, tenant_id, req, uctx)
        
        orders_requests_total.labels(endpoint="create_order", status="ok").inc()
        orders_request_duration.labels(endpoint="create_order").observe(time.time() - start)
        
        return result
        
    except ValueError as e:
        orders_requests_total.labels(endpoint="create_order", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        orders_requests_total.labels(endpoint="create_order", status="fail").inc()
        logger.error("Order creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/orders")
async def list_orders(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: SessionLocal = Depends(get_db)
):
    """List orders for a tenant"""
    try:
        orders = db.execute(
            text("SELECT * FROM orders_v2 WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        ).fetchall()
        
        return [dict(order._mapping) for order in orders]
        
    except Exception as e:
        logger.error("Failed to list orders", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get order by ID"""
    try:
        order = db.execute(
            text("SELECT * FROM orders_v2 WHERE order_id = :id"),
            {"id": order_id}
        ).fetchone()
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        return dict(order._mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/orders/{order_id}")
async def update_order(
    order_id: str,
    req: OrderUpdateRequest,
    db: SessionLocal = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Update order"""
    try:
        # Build update query
        updates = []
        params = {"id": order_id}
        
        if req.order_status:
            updates.append("order_status = :order_status")
            params["order_status"] = req.order_status
        
        if req.payment_status:
            updates.append("payment_status = :payment_status")
            params["payment_status"] = req.payment_status
        
        if req.fulfillment_status:
            updates.append("fulfillment_status = :fulfillment_status")
            params["fulfillment_status"] = req.fulfillment_status
        
        if req.metadata:
            updates.append("metadata = :metadata")
            params["metadata"] = json.dumps(req.metadata)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        updates.append("updated_at = NOW()")
        
        db.execute(
            text(f"UPDATE orders_v2 SET {', '.join(updates)} WHERE order_id = :id"),
            params
        )
        db.commit()
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "UPDATE", "order", order_id, req.dict())
        
        return {"order_id": order_id, "updated": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    db: SessionLocal = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Cancel order"""
    try:
        db.execute(
            text("UPDATE orders_v2 SET order_status = 'cancelled', updated_at = NOW() WHERE order_id = :id"),
            {"id": order_id}
        )
        db.commit()
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CANCEL", "order", order_id, {})
        
        return {"order_id": order_id, "cancelled": True}
        
    except Exception as e:
        logger.error("Failed to cancel order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_order_fulfillment(self, order_id: str, fulfillment_data: Dict[str, Any]):
    """Process order fulfillment asynchronously"""
    try:
        with SessionLocal() as db:
            # Get order
            order = db.execute(text("""
                SELECT * FROM orders_v2 WHERE order_id = :id
            """), {"id": order_id}).fetchone()
            
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            # Process fulfillment logic here
            logger.info(f"Processing order fulfillment for order {order_id}")
            
            # Update status
            db.execute(text("""
                UPDATE orders_v2 
                SET fulfillment_status = 'fulfilled', updated_at = NOW()
                WHERE order_id = :id
            """), {"id": order_id})
            
            db.commit()
            
            # Update metrics
            orders_operations_total.labels(operation="fulfillment", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process order fulfillment for order {order_id}: {e}")
        orders_operations_total.labels(operation="fulfillment", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_order_cancellation(self, order_id: str, cancellation_reason: str):
    """Process order cancellation asynchronously"""
    try:
        with SessionLocal() as db:
            # Get order
            order = db.execute(text("""
                SELECT * FROM orders_v2 WHERE order_id = :id
            """), {"id": order_id}).fetchone()
            
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            # Process cancellation logic here
            logger.info(f"Processing order cancellation for order {order_id}, reason: {cancellation_reason}")
            
            # Update status
            db.execute(text("""
                UPDATE orders_v2 
                SET order_status = 'cancelled', updated_at = NOW()
                WHERE order_id = :id
            """), {"id": order_id})
            
            db.commit()
            
            # Update metrics
            orders_operations_total.labels(operation="cancellation", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process order cancellation for order {order_id}: {e}")
        orders_operations_total.labels(operation="cancellation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_orders(self):
    """Clean up old orders"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            
            # Clean up old completed orders
            order_result = db.execute(text("""
                DELETE FROM orders_v2 
                WHERE created_at < :cutoff_date AND order_status IN ('completed', 'cancelled')
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {order_result.rowcount} old orders")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old orders: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8224")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )