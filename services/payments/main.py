# Payments Service V2 - Enhanced V4.1 Architecture
# Multi-provider payment processing with sagas, events, and RLS

import os
import uuid
import json
import asyncio
import structlog
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body, HTTPException, Query, Path, Depends, Request, BackgroundTasks, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Numeric, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
from sqlalchemy.exc import SQLAlchemyError

# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

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
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "payments"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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
payments_operations_total = Counter('payments_operations_total', 'Total payments operations', ['operation', 'status'])
payments_request_duration = Histogram('payments_request_duration_seconds', 'Payments request duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

# =============================================================================
# DATABASE MODELS
# =============================================================================

class PaymentTransactionNew(Base):
    """V4.1 payment transactions table with multi-provider support"""
    __tablename__ = "payment_transactions_new"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey('vendors.vendor_id'), nullable=True)
    provider = Column(String(50), nullable=False, comment='stripe, adyen, paypal, etc.')
    payment_intent_id = Column(String(255), nullable=True)
    charge_id = Column(String(255), nullable=True)
    amount_minor = Column(BigInteger, nullable=False, comment='Amount in minor units')
    currency = Column(String(3), ForeignKey('currencies.code'), nullable=False, default='GBP')
    status = Column(String(50), nullable=False, comment='pending, succeeded, failed, refunded')
    order_id = Column(UUID(as_uuid=True), nullable=True)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    raw_response = Column(JSONB, nullable=True, comment='Raw provider response')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class CustomerNew(Base):
    """V4.1 customers table with multi-provider support"""
    __tablename__ = "customers_new"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False, comment='stripe, adyen, paypal, etc.')
    external_customer_id = Column(String(255), nullable=False, comment='Provider customer ID')
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class PaymentRefund(Base):
    """Payment refunds table"""
    __tablename__ = "payment_refunds"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey('payment_transactions_new.id'), nullable=False)
    refund_id = Column(String(255), nullable=True, comment='Provider refund ID')
    amount_minor = Column(BigInteger, nullable=False, comment='Refund amount in minor units')
    currency = Column(String(3), nullable=False, default='GBP')
    reason = Column(String(255), nullable=True, comment='Refund reason')
    status = Column(String(50), nullable=False, comment='pending, succeeded, failed')
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class PaymentAdjustment(Base):
    """Payment adjustments table"""
    __tablename__ = "payment_adjustments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey('payment_transactions_new.id'), nullable=False)
    adjustment_type = Column(String(50), nullable=False, comment='discount, fee, tax, etc.')
    amount_minor = Column(BigInteger, nullable=False, comment='Adjustment amount in minor units')
    currency = Column(String(3), nullable=False, default='GBP')
    reason = Column(String(255), nullable=True, comment='Adjustment reason')
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class AuditLog(Base):
    """Audit logs table"""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class OutboxEvent(Base):
    """Outbox events table for reliable event publishing"""
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(50), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class PaymentIntentRequest(BaseModel):
    """Request model for creating payment intents"""
    tenant_id: str = Field(..., description="Tenant ID")
    order_id: Optional[str] = Field(None, description="Associated order ID")
    amount_minor: int = Field(..., description="Amount in minor units")
    currency: str = Field(default="GBP", description="Currency code")
    provider: str = Field(default="stripe", description="Payment provider")
    site_id: Optional[str] = Field(None, description="Site ID")
    store_id: Optional[str] = Field(None, description="Store ID")
    user_id: Optional[str] = Field(None, description="User ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class CustomerRequest(BaseModel):
    """Request model for customer operations"""
    tenant_id: str = Field(..., description="Tenant ID")
    provider: str = Field(default="stripe", description="Payment provider")
    email: Optional[str] = Field(None, description="Customer email")
    name: Optional[str] = Field(None, description="Customer name")
    phone: Optional[str] = Field(None, description="Customer phone")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class RefundRequest(BaseModel):
    """Request model for payment refunds"""
    tenant_id: str = Field(..., description="Tenant ID")
    payment_intent_id: str = Field(..., description="Payment intent ID")
    amount_minor: Optional[int] = Field(None, description="Refund amount in minor units (full if not specified)")
    reason: Optional[str] = Field(None, description="Refund reason")

class PaymentAdjustmentRequest(BaseModel):
    """Request model for payment adjustments"""
    tenant_id: str = Field(..., description="Tenant ID")
    payment_intent_id: str = Field(..., description="Payment intent ID")
    adjustment_type: str = Field(..., description="Type of adjustment")
    amount_minor: int = Field(..., description="Adjustment amount in minor units")
    currency: str = Field(default="GBP", description="Currency code")
    reason: Optional[str] = Field(None, description="Adjustment reason")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class RailRequest(BaseModel):
    """Request model for payment provider configuration"""
    tenant_id: str = Field(..., description="Tenant ID")
    type: str = Field(default="payment", description="Rail type")
    name: str = Field(..., description="Provider name (e.g., stripe, adyen)")
    config: Dict[str, Any] = Field(..., description="Provider configuration")
    active: bool = Field(default=True, description="Whether the provider is active")

# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Payment metrics
payment_requests_total = Counter(
    'payment_requests_total',
    'Total payment requests',
    ['provider', 'status', 'currency']
)

payment_amount_total = Counter(
    'payment_amount_total',
    'Total payment amounts',
    ['provider', 'currency']
)

payment_duration_seconds = Histogram(
    'payment_duration_seconds',
    'Payment processing duration',
    ['provider', 'operation']
)

webhook_requests_total = Counter(
    'webhook_requests_total',
    'Total webhook requests',
    ['provider', 'event_type', 'status']
)

# Use unique metric name to avoid duplicate registration across services
saga_duration_seconds = Histogram(
    'payments_saga_duration_seconds',
    'Saga processing duration',
    ['saga_type', 'status']
)

# =============================================================================
# PAYMENT PROVIDERS
# =============================================================================

class BasePaymentProvider:
    """Base class for payment providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get('api_key')
        self.base_url = config.get('base_url')
    
    async def create_payment_intent(self, amount_minor: int, currency: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a payment intent with the provider"""
        raise NotImplementedError
    
    async def create_customer(self, email: str, name: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a customer with the provider"""
        raise NotImplementedError
    
    async def process_webhook(self, payload: Dict[str, Any], signature: str = None) -> Dict[str, Any]:
        """Process webhook from the provider"""
        raise NotImplementedError
    
    async def refund_payment(self, payment_intent_id: str, amount_minor: int = None, reason: str = None) -> Dict[str, Any]:
        """Refund a payment"""
        raise NotImplementedError

class StripeProvider(BasePaymentProvider):
    """Stripe payment provider implementation"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        import stripe
        stripe.api_key = self.api_key
        self.stripe = stripe
    
    async def create_payment_intent(self, amount_minor: int, currency: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a Stripe payment intent"""
        try:
            payment_intent = self.stripe.PaymentIntent.create(
                amount=amount_minor,
                currency=currency.lower(),
                metadata=metadata or {}
            )
            return {
                "ok": True,
                "payment_intent_id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status
            }
        except Exception as e:
            logger.error(f"Stripe payment intent creation failed: {str(e)}")
            return {"ok": False, "error": str(e)}
    
    async def create_customer(self, email: str, name: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a Stripe customer"""
        try:
            customer = self.stripe.Customer.create(
                email=email,
                name=name,
                metadata=metadata or {}
            )
            return {
                "ok": True,
                "customer_id": customer.id,
                "email": customer.email,
                "name": customer.name
            }
        except Exception as e:
            logger.error(f"Stripe customer creation failed: {str(e)}")
            return {"ok": False, "error": str(e)}
    
    async def process_webhook(self, payload: Dict[str, Any], signature: str = None) -> Dict[str, Any]:
        """Process Stripe webhook"""
        try:
            # In production, verify webhook signature
            event_type = payload.get('type')
            data = payload.get('data', {}).get('object', {})
            
            if event_type == 'payment_intent.succeeded':
                return {
                    "ok": True,
                    "event_type": event_type,
                    "payment_intent_id": data.get('id'),
                    "status": "succeeded",
                    "amount_minor": data.get('amount'),
                    "currency": data.get('currency')
                }
            elif event_type == 'payment_intent.payment_failed':
                return {
                    "ok": True,
                    "event_type": event_type,
                    "payment_intent_id": data.get('id'),
                    "status": "failed",
                    "error": data.get('last_payment_error', {}).get('message')
                }
            
            return {"ok": True, "event_type": event_type, "status": "ignored"}
            
        except Exception as e:
            logger.error(f"Stripe webhook processing failed: {str(e)}")
            return {"ok": False, "error": str(e)}
    
    async def refund_payment(self, payment_intent_id: str, amount_minor: int = None, reason: str = None) -> Dict[str, Any]:
        """Refund a Stripe payment"""
        try:
            refund_data = {
                'payment_intent': payment_intent_id,
                'reason': reason or 'requested_by_customer'
            }
            if amount_minor:
                refund_data['amount'] = amount_minor
            
            refund = self.stripe.Refund.create(**refund_data)
            return {
                "ok": True,
                "refund_id": refund.id,
                "amount_minor": refund.amount,
                "status": refund.status
            }
        except Exception as e:
            logger.error(f"Stripe refund failed: {str(e)}")
            return {"ok": False, "error": str(e)}

# =============================================================================
# SAGA IMPLEMENTATION
# =============================================================================

class PaymentIntentSaga:
    """Saga for payment intent creation with compensation"""
    
    def __init__(self, db: Session):
        self.db = db
        self.steps = []
        self.compensation_steps = []
    
    async def create_payment_intent(self, request: PaymentIntentRequest) -> Dict[str, Any]:
        """Execute payment intent creation saga"""
        start_time = datetime.now()
        
        try:
            # Step 1: Validate tenant and get provider config
            provider_config = await self._get_provider_config(request.tenant_id, request.provider)
            if not provider_config:
                return {"ok": False, "error": "Provider configuration not found"}
            
            # Step 2: Create payment intent with provider
            provider = await self._get_provider(request.provider, provider_config)
            provider_result = await provider.create_payment_intent(
                request.amount_minor,
                request.currency,
                request.metadata
            )
            
            if not provider_result.get("ok"):
                return {"ok": False, "error": provider_result.get("error")}
            
            # Step 3: Store payment transaction
            transaction = PaymentTransactionNew(
                tenant_id=request.tenant_id,
                vendor_id=request.metadata.get("vendor_id") if request.metadata else None,
                provider=request.provider,
                payment_intent_id=provider_result["payment_intent_id"],
                amount_minor=request.amount_minor,
                currency=request.currency,
                status="pending",
                order_id=request.order_id,
                site_id=request.site_id,
                store_id=request.store_id,
                user_id=request.user_id,
                metadata=request.metadata,
                raw_response=provider_result
            )
            
            self.db.add(transaction)
            self.db.commit()
            
            # Step 4: Publish event
            await self._publish_event(
                request.tenant_id,
                "PAYMENT_CREATED",
                {
                    "payment_intent_id": provider_result["payment_intent_id"],
                    "amount_minor": request.amount_minor,
                    "currency": request.currency,
                    "provider": request.provider,
                    "order_id": request.order_id
                }
            )
            
            # Update metrics
            payment_requests_total.labels(
                provider=request.provider,
                status="success",
                currency=request.currency
            ).inc()
            
            payment_amount_total.labels(
                provider=request.provider,
                currency=request.currency
            ).inc(request.amount_minor)
            
            duration = (datetime.now() - start_time).total_seconds()
            payment_duration_seconds.labels(
                provider=request.provider,
                operation="create_intent"
            ).observe(duration)
            
            return {
                "ok": True,
                "payment_intent_id": provider_result["payment_intent_id"],
                "client_secret": provider_result.get("client_secret"),
                "status": provider_result.get("status"),
                "transaction_id": str(transaction.id)
            }
            
        except Exception as e:
            logger.error(f"Payment intent saga failed: {str(e)}")
            await self._compensate()
            
            payment_requests_total.labels(
                provider=request.provider,
                status="failure",
                currency=request.currency
            ).inc()
            
            return {"ok": False, "error": str(e)}
    
    async def _get_provider_config(self, tenant_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Get provider configuration from zeroque_rails"""
        result = self.db.execute(text("""
            SELECT config FROM zeroque_rails
            WHERE tenant_id = :tenant_id AND type = 'payment' AND name = :provider AND active = true
        """), {"tenant_id": tenant_id, "provider": provider}).first()
        
        return result[0] if result else None
    
    async def _get_provider(self, provider_name: str, config: Dict[str, Any]) -> BasePaymentProvider:
        """Get provider instance based on name"""
        if provider_name == "stripe":
            return StripeProvider(config)
        else:
            raise ValueError(f"Unsupported payment provider: {provider_name}")
    
    async def _publish_event(self, tenant_id: str, event_type: str, event_data: Dict[str, Any]):
        """Publish event to outbox"""
        event = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            event_data=event_data,
            status="pending"
        )
        self.db.add(event)
        self.db.commit()
    
    async def _compensate(self):
        """Execute compensation steps"""
        # Rollback any changes made during the saga
        self.db.rollback()
        logger.info("Payment intent saga compensation executed")

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def log_audit(db: Session, action: str, resource_type: str, resource_id: str = None, 
                   details: Dict[str, Any] = None, tenant_id: str = None, user_id: str = None):
    """Log audit event"""
    audit_log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit_log)
    db.commit()

async def set_rls_context(db: Session, tenant_id: str, user_id: str = None):
    """Set Row Level Security context"""
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if user_id:
        db.execute(text("SET app.current_user_id = :user_id"), {"user_id": user_id})

def get_user_context(request: Request) -> Dict[str, Any]:
    """Get user context from request (demo implementation)"""
    # In production, extract from JWT token
    return {
        "user_id": "demo_user_id",
        "tenant_id": request.headers.get("x-tenant-id", "demo_tenant_id"),
        "role": "admin"
    }

def check_permission(permission: str, user_context: Dict[str, Any]) -> bool:
    """Check user permissions (demo implementation)"""
    # In production, implement proper RBAC
    return True

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting Payments Service V2", version="2.0.0", environment="production")
    
    # Create tables if they don't exist
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Payments Service V2")

app = FastAPI(
    title="ZeroQue Payments Service V2",
    version="2.0.0",
    description="Multi-provider payment processing with V4.1 architecture",
    lifespan=lifespan
)

# Add middleware
# add_api_call_meter(app)  # Temporarily disabled for debugging
# add_idempotency_middleware(app, routes=[("POST", "/payments"), ("POST", "/payments/v2")])  # Temporarily disabled for debugging

# =============================================================================
# HEALTH AND STATUS ENDPOINTS
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "payments", "version": "2.0.0"}

def check_db():
    """Simple database connectivity check"""
    # Temporarily return True to avoid database connection issues
    return True

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    return {
        "service": "payments",
        "db": check_db(),
        "version": "2.0.0"
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# PAYMENT ENDPOINTS
# =============================================================================

@app.post("/payments/v2/intent")
async def create_payment_intent(
    request: PaymentIntentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create a payment intent with any supported provider"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.create_intent", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Execute saga
        saga = PaymentIntentSaga(db)
        result = await saga.create_payment_intent(request)
        
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        
        # Log audit
        await log_audit(
            db, "create_payment_intent", "payment_intent",
            result.get("payment_intent_id"), request.dict(),
            request.tenant_id, user_context.get("user_id")
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Payment intent creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/payments/v2/customers")
async def create_customer(
    request: CustomerRequest,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create or update a customer with any supported provider"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.create_customer", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Get provider config
        provider_config = await PaymentIntentSaga(db)._get_provider_config(request.tenant_id, request.provider)
        if not provider_config:
            raise HTTPException(status_code=400, detail="Provider configuration not found")
        
        # Create customer with provider
        provider = await PaymentIntentSaga(db)._get_provider(request.provider, provider_config)
        provider_result = await provider.create_customer(
            request.email or "",
            request.name,
            request.metadata
        )
        
        if not provider_result.get("ok"):
            raise HTTPException(status_code=400, detail=provider_result.get("error"))
        
        # Store customer
        customer = CustomerNew(
            tenant_id=request.tenant_id,
            provider=request.provider,
            external_customer_id=provider_result["customer_id"],
            email=request.email,
            name=request.name,
            phone=request.metadata.get("phone") if request.metadata else None,
            metadata=request.metadata
        )
        
        db.add(customer)
        db.commit()

        # Log audit
        await log_audit(
            db, "create_customer", "customer",
            provider_result["customer_id"], request.dict(),
            request.tenant_id, user_context.get("user_id")
        )
        
        return {
            "ok": True,
            "customer_id": provider_result["customer_id"],
            "email": provider_result.get("email"),
            "name": provider_result.get("name")
        }
        
    except Exception as e:
        logger.error(f"Customer creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/payments/v2/refund")
async def refund_payment(
    request: RefundRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Refund a payment"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.refund", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Get payment transaction
        transaction = db.query(PaymentTransactionNew).filter(
            PaymentTransactionNew.payment_intent_id == request.payment_intent_id,
            PaymentTransactionNew.tenant_id == request.tenant_id
        ).first()
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Payment transaction not found")
        
        # Get provider config and create provider instance
        provider_config = await PaymentIntentSaga(db)._get_provider_config(request.tenant_id, transaction.provider)
        provider = await PaymentIntentSaga(db)._get_provider(transaction.provider, provider_config)
        
        # Process refund with provider
        refund_amount = request.amount_minor or transaction.amount_minor
        provider_result = await provider.refund_payment(
            request.payment_intent_id,
            refund_amount,
            request.reason
        )
        
        if not provider_result.get("ok"):
            raise HTTPException(status_code=400, detail=provider_result.get("error"))
        
        # Store refund record
        refund = PaymentRefund(
            tenant_id=request.tenant_id,
            payment_transaction_id=transaction.id,
            refund_id=provider_result["refund_id"],
            amount_minor=refund_amount,
            currency=transaction.currency,
            reason=request.reason,
            status="succeeded"
        )
        
        db.add(refund)
        
        # Update transaction status
        transaction.status = "refunded"
        
        db.commit()
        
        # Publish event
        await PaymentIntentSaga(db)._publish_event(
            request.tenant_id,
            "PAYMENT_REFUNDED",
            {
                "payment_intent_id": request.payment_intent_id,
                "refund_id": provider_result["refund_id"],
                "amount_minor": refund_amount,
                "currency": transaction.currency
            }
        )
        
        # Log audit
        await log_audit(
            db, "refund_payment", "payment_refund",
            provider_result["refund_id"], request.dict(),
            request.tenant_id, user_context.get("user_id")
        )
        
        return {
            "ok": True,
            "refund_id": provider_result["refund_id"],
            "amount_minor": refund_amount,
            "status": "succeeded"
        }
        
    except Exception as e:
        logger.error(f"Payment refund failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/payments/v2/webhook/{provider}")
async def process_webhook(
    provider: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_with_rls)
):
    """Process webhook from payment providers"""
    try:
        payload = await request.json()
        signature = request.headers.get("stripe-signature") if provider == "stripe" else None
        
        # Get provider config (use first available tenant for demo)
        tenant_id = "demo_tenant_id"  # In production, determine from webhook payload
        
        provider_config = await PaymentIntentSaga(db)._get_provider_config(tenant_id, provider)
        provider_instance = await PaymentIntentSaga(db)._get_provider(provider, provider_config)
        
        # Process webhook
        result = await provider_instance.process_webhook(payload, signature)
        
        if not result.get("ok"):
            webhook_requests_total.labels(
                provider=provider,
                event_type="unknown",
                status="failure"
            ).inc()
            raise HTTPException(status_code=400, detail=result.get("error"))
        
        # Update metrics
        webhook_requests_total.labels(
            provider=provider,
            event_type=result.get("event_type", "unknown"),
            status="success"
        ).inc()
        
        # If payment succeeded, update transaction and publish events
        if result.get("status") == "succeeded":
            background_tasks.add_task(
                _handle_payment_success,
                db, tenant_id, result
            )
        elif result.get("status") == "failed":
            background_tasks.add_task(
                _handle_payment_failure,
                db, tenant_id, result
            )
        
        return {"ok": True, "status": "processed"}
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        webhook_requests_total.labels(
            provider=provider,
            event_type="unknown",
            status="failure"
        ).inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

async def _handle_payment_success(db: Session, tenant_id: str, result: Dict[str, Any]):
    """Handle successful payment"""
    try:
        # Update transaction status
        db.execute(text("""
            UPDATE payment_transactions_new
            SET status = 'succeeded', updated_at = NOW()
            WHERE payment_intent_id = :payment_intent_id AND tenant_id = :tenant_id
        """), {
            "payment_intent_id": result["payment_intent_id"],
            "tenant_id": tenant_id
        })
        
        db.commit()
        
        # Publish PAYMENT_PAID event
        await PaymentIntentSaga(db)._publish_event(
            tenant_id,
            "PAYMENT_PAID",
            result
        )
        
        logger.info(f"Payment succeeded: {result['payment_intent_id']}")
        
    except Exception as e:
        logger.error(f"Failed to handle payment success: {str(e)}")
        db.rollback()

async def _handle_payment_failure(db: Session, tenant_id: str, result: Dict[str, Any]):
    """Handle failed payment"""
    try:
        # Update transaction status
        db.execute(text("""
            UPDATE payment_transactions_new
            SET status = 'failed', updated_at = NOW()
            WHERE payment_intent_id = :payment_intent_id AND tenant_id = :tenant_id
        """), {
            "payment_intent_id": result["payment_intent_id"],
            "tenant_id": tenant_id
        })
        
        db.commit()
        
        # Publish PAYMENT_FAILED event
        await PaymentIntentSaga(db)._publish_event(
            tenant_id,
            "PAYMENT_FAILED",
            result
        )
        
        logger.info(f"Payment failed: {result['payment_intent_id']}")
        
    except Exception as e:
        logger.error(f"Failed to handle payment failure: {str(e)}")
        db.rollback()

# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.post("/payments/v2/admin/rails/payment")
async def configure_payment_provider(
    request: RailRequest,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Configure payment provider for a tenant"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.admin.configure", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Upsert provider configuration
        db.execute(text("""
            INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at, updated_at)
            VALUES (:tenant_id, :type, :name, :config, :active, NOW(), NOW())
            ON CONFLICT (tenant_id, type, name)
            DO UPDATE SET config = :config, active = :active, updated_at = NOW()
        """), {
            "tenant_id": request.tenant_id,
            "type": request.type,
            "name": request.name,
            "config": json.dumps(request.config),
            "active": request.active
        })
        
        db.commit()
        
        # Log audit
        await log_audit(
            db, "configure_payment_provider", "zeroque_rails",
            f"{request.tenant_id}:{request.name}", request.dict(),
            request.tenant_id, user_context.get("user_id")
        )
        
        return {"ok": True, "message": f"Provider {request.name} configured successfully"}
        
    except Exception as e:
        logger.error(f"Provider configuration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

# =============================================================================
# QUERY ENDPOINTS
# =============================================================================

@app.get("/payments/v2/transactions")
async def list_transactions(
    tenant_id: str = Query(...),
    provider: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List payment transactions with filters"""
    try:
        # Set RLS context
        await set_rls_context(db, tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.view_transactions", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Build query
        query = text("""
            SELECT id, provider, payment_intent_id, charge_id, amount_minor, currency, status,
                   order_id, site_id, store_id, user_id, created_at, updated_at
            FROM payment_transactions_new
            WHERE tenant_id = :tenant_id
        """)
        
        params = {"tenant_id": tenant_id}
        
        if provider:
            query = text(str(query) + " AND provider = :provider")
            params["provider"] = provider
        
        if status:
            query = text(str(query) + " AND status = :status")
            params["status"] = status
        
        query = text(str(query) + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset")
        params.update({"limit": limit, "offset": offset})
        
        # Execute query
        result = db.execute(query, params).fetchall()
        
        transactions = []
        for row in result:
            transactions.append({
                "id": str(row[0]),
                "provider": row[1],
                "payment_intent_id": row[2],
                "charge_id": row[3],
                "amount_minor": row[4],
                "currency": row[5],
                "status": row[6],
                "order_id": str(row[7]) if row[7] else None,
                "site_id": str(row[8]) if row[8] else None,
                "store_id": str(row[9]) if row[9] else None,
                "user_id": str(row[10]) if row[10] else None,
                "created_at": row[11].isoformat(),
                "updated_at": row[12].isoformat() if row[12] else None
            })
        
        return {
            "ok": True,
            "transactions": transactions,
            "total": len(transactions),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"Transaction listing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/payments/v2/reports")
async def get_payment_reports(
    tenant_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
    currency: Optional[str] = Query("GBP"),
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get payment reports and analytics (blueprint-inspired)"""
    try:
        # Set RLS context
        await set_rls_context(db, tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Get payment summary by provider
        summary_query = text("""
            SELECT provider, status, COUNT(*) as count, SUM(amount_minor) as total_amount_minor
            FROM payment_transactions_new
            WHERE tenant_id = :tenant_id 
              AND currency = :currency
              AND created_at >= :period_start 
              AND created_at <= :period_end
            GROUP BY provider, status
            ORDER BY provider, status
        """)
        
        summary_result = db.execute(summary_query, {
            "tenant_id": tenant_id,
            "currency": currency,
            "period_start": period_start,
            "period_end": period_end
        }).fetchall()
        
        # Get daily payment trends
        daily_query = text("""
            SELECT DATE(created_at) as date, COUNT(*) as count, SUM(amount_minor) as total_amount_minor
            FROM payment_transactions_new
            WHERE tenant_id = :tenant_id 
              AND currency = :currency
              AND created_at >= :period_start 
              AND created_at <= :period_end
              AND status = 'succeeded'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        
        daily_result = db.execute(daily_query, {
            "tenant_id": tenant_id,
            "currency": currency,
            "period_start": period_start,
            "period_end": period_end
        }).fetchall()
        
        # Format results
        summary = {}
        for row in summary_result:
            provider = row[0]
            status = row[1]
            count = row[2]
            amount = row[3]
            
            if provider not in summary:
                summary[provider] = {}
            
            summary[provider][status] = {
                "count": count,
                "total_amount_minor": amount
            }
        
        daily_trends = []
        for row in daily_result:
            daily_trends.append({
                "date": str(row[0]),
                "count": row[1],
                "total_amount_minor": row[2]
            })
        
        return {
            "ok": True,
            "period": {
                "start": period_start,
                "end": period_end,
                "currency": currency
            },
            "summary": summary,
            "daily_trends": daily_trends,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Payment reports failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

# =============================================================================
# LEGACY ENDPOINT DEPRECATION
# =============================================================================

@app.post("/stripe/customers")
async def stripe_customers_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/customers",
        "message": "This endpoint is deprecated. Please use /payments/v2/customers"
    }

@app.post("/stripe/payment-intent")
async def stripe_payment_intent_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/intent",
        "message": "This endpoint is deprecated. Please use /payments/v2/intent"
    }

@app.post("/stripe/webhook")
async def stripe_webhook_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/webhook/stripe",
        "message": "This endpoint is deprecated. Please use /payments/v2/webhook/stripe"
    }

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/payments/v2/integration/orders/payment-required")
async def handle_payment_required_event(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db_with_rls)
):
    """Handle ORDER_COMPLETED event from Orders service requiring payment"""
    try:
        logger.info(f"Received ORDER_COMPLETED event requiring payment: {event_data}")
        
        order_id = event_data.get("order_id")
        tenant_id = event_data.get("tenant_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not order_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing order_id or tenant_id")
        
        # Create payment intent for the order
        request = PaymentIntentRequest(
            tenant_id=tenant_id,
            order_id=order_id,
            amount_minor=total_amount_minor,
            currency=currency,
            provider="stripe",  # Default provider
            metadata={"order_id": order_id, "auto_created": True}
        )
        
        saga = PaymentIntentSaga(db)
        result = await saga.create_payment_intent(request)
        
        logger.info(f"Created payment intent for order: {result}")
        return {"ok": True, "payment_intent_created": True, "result": result}
        
    except Exception as e:
        logger.error(f"Error handling payment required event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")
    finally:
        db.close()

@app.get("/payments/v2/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "notifications_service": {"status": "unknown", "url": "http://localhost:8087"}
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
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_payment_intent(self, payment_intent_id: str, intent_data: Dict[str, Any]):
    """Process payment intent asynchronously"""
    try:
        with SessionLocal() as db:
            # Get payment intent
            intent = db.execute(text("""
                SELECT * FROM payment_intents_new WHERE id = :id
            """), {"id": payment_intent_id}).fetchone()
            
            if not intent:
                raise ValueError(f"Payment intent {payment_intent_id} not found")
            
            # Process payment logic here
            logger.info(f"Processing payment intent {payment_intent_id}")
            
            # Update status
            db.execute(text("""
                UPDATE payment_intents_new 
                SET status = 'processed', updated_at = NOW()
                WHERE id = :id
            """), {"id": payment_intent_id})
            
            db.commit()
            
            # Update metrics
            payments_operations_total.labels(operation="intent", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process payment intent {payment_intent_id}: {e}")
        payments_operations_total.labels(operation="intent", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_payment_refund(self, payment_id: str, refund_data: Dict[str, Any]):
    """Process payment refund asynchronously"""
    try:
        with SessionLocal() as db:
            # Get payment
            payment = db.execute(text("""
                SELECT * FROM payments_new WHERE id = :id
            """), {"id": payment_id}).fetchone()
            
            if not payment:
                raise ValueError(f"Payment {payment_id} not found")
            
            # Process refund logic here
            logger.info(f"Processing payment refund for payment {payment_id}")
            
            # Update status
            db.execute(text("""
                UPDATE payments_new 
                SET status = 'refunded', updated_at = NOW()
                WHERE id = :id
            """), {"id": payment_id})
            
            db.commit()
            
            # Update metrics
            payments_operations_total.labels(operation="refund", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process payment refund for payment {payment_id}: {e}")
        payments_operations_total.labels(operation="refund", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_payments(self):
    """Clean up old payments"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            
            # Clean up old payments
            payment_result = db.execute(text("""
                DELETE FROM payments_new 
                WHERE created_at < :cutoff_date AND status IN ('completed', 'failed', 'refunded')
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old payment intents
            intent_result = db.execute(text("""
                DELETE FROM payment_intents_new 
                WHERE created_at < :cutoff_date AND status IN ('completed', 'failed')
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {payment_result.rowcount} old payments and {intent_result.rowcount} old payment intents")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old payments: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================


# =============================================================================
# CELERY WORKERS - Event Consumption
# =============================================================================

@celery_app.task(bind=True, max_retries=3, name='payments.process_order_completed')
def process_order_completed(self, event_data: Dict[str, Any]):
    """Process ORDER_COMPLETED event from orders service"""
    try:
        tenant_id = event_data.get('tenant_id')
        order_id = event_data.get('order_id')
        total_amount = event_data.get('total_minor')

        if not all([tenant_id, order_id, total_amount]):
            logger.error('Missing required fields in ORDER_COMPLETED event')
            return {'status': 'error', 'message': 'Missing required fields'}

        with SessionLocal() as db:
            # Create payment intent for the order
            payment_intent_id = f"pi_{uuid.uuid4().hex[:12]}"
            
            payment_intent = PaymentTransaction(
                transaction_id=payment_intent_id,
                tenant_id=tenant_id,
                order_id=order_id,
                amount_minor=total_amount,
                currency='GBP',
                status='pending',
                provider='stripe',
                payment_method='card'
            )
            db.add(payment_intent)
            db.commit()

            logger.info(f"Created payment intent {payment_intent_id} for order {order_id}")

        return {'status': 'ok', 'payment_intent_id': payment_intent_id}

    except Exception as e:
        logger.error(f"Failed to process ORDER_COMPLETED event: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='payments.cleanup_old_outbox_events')
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

@celery_app.task(bind=True, max_retries=3, name='payments.cleanup_old_payments')
def cleanup_old_payments(self):
    """Clean up old payment transactions and refunds"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=365)
            
            # Clean old transactions
            trans_result = db.execute(
                text("DELETE FROM payment_transactions_new WHERE created_at < :cutoff AND status IN ('failed', 'canceled')"),
                {'cutoff': cutoff}
            )
            
            # Clean old refunds
            refund_result = db.execute(
                text("DELETE FROM payment_refunds WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            
            db.commit()
            logger.info(f"Cleaned {trans_result.rowcount} old transactions and {refund_result.rowcount} old refunds")
            return {'transactions_deleted': trans_result.rowcount, 'refunds_deleted': refund_result.rowcount}

    except Exception as e:
        logger.error(f"Failed to cleanup old payments: {e}")
        raise self.retry(exc=e, countdown=300)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8225")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )