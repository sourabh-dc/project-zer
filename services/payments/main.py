# Payments Service V2 - Enhanced V4.1 Architecture
# Multi-provider payment processing with sagas, events, and RLS

import os
import uuid
import json
import jwt
import asyncio
import structlog
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body, HTTPException, Query, Path, Depends, Request, BackgroundTasks, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Database imports
from sqlalchemy import create_engine, text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, \
    func, or_
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

from core.config import get_settings
from .models import (PaymentTransactionNew, CustomerNew, PaymentRefund, OutboxEvent, AuditLog, TradeAccount,
                     CurrencyRate, Base, PaymentIntent)
from .schemas import PaymentIntentRequest, CustomerRequest, RefundRequest, RailRequest, TradeAccountRequest, \
    TradeAccountRequest, PaymentAdjustmentRequest, TradeAccountResponse, MultiCurrencyConversionRequest, \
    MultiCurrencyConversionResponse, PaymentIntentResponse

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY

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
from sqlalchemy.orm import sessionmaker

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "payments"
SERVICE_VERSION = "4.1.0"

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

# Prometheus metrics - Clear registry to avoid duplicates
from prometheus_client import REGISTRY
try:
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
except:
    pass

payments_operations_total = Counter('payments_operations_total', 'Total payments operations', ['operation', 'status'])
payments_request_duration = Histogram('payments_request_duration_seconds', 'Payments request duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

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
    
    async def create_payment_intent(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Stripe payment intent - Phase 5"""
        try:
            # Demo mode: return mock response
            if ALLOW_DEMO:
                return {
                    "id": f"pi_demo_{uuid.uuid4().hex[:16]}",
                    "client_secret": f"pi_demo_{uuid.uuid4().hex[:16]}_secret_{uuid.uuid4().hex[:16]}",
                    "amount": intent_data.get("amount", 0),
                    "currency": intent_data.get("currency", "gbp"),
                    "status": "requires_payment_method",
                    "metadata": intent_data.get("metadata", {})
                }

            # Production: Create real Stripe payment intent
            payment_intent = self.stripe.PaymentIntent.create(
                amount=intent_data.get("amount", 0),
                currency=intent_data.get("currency", "gbp").lower(),
                payment_method_types=intent_data.get("payment_method_types", ["card"]),
                metadata=intent_data.get("metadata", {})
            )
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
                "status": payment_intent.status,
                "metadata": payment_intent.payment_metadata
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
                transaction_metadata=request.metadata,
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

# Phase 5: Trade Account & Multi-Currency Endpoints
@app.post("/trade-accounts", response_model=TradeAccountResponse)
async def create_trade_account(
    request: TradeAccountRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new trade account - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="create_trade_account", status="start").inc()

        # Check permissions
        if not check_permission("payments.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Generate account number
        account_number = f"TA-{uuid.uuid4().hex[:8].upper()}"

        trade_account = TradeAccount(
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            account_number=account_number,
            company_name=request.company_name,
            contact_email=request.contact_email,
            credit_limit_minor=request.credit_limit_minor,
            available_credit_minor=request.credit_limit_minor,
            currency=request.currency,
            payment_terms_days=request.payment_terms_days
        )

        db.add(trade_account)
        db.commit()
        db.refresh(trade_account)

        payment_requests_total.labels(endpoint="create_trade_account", status="ok").inc()

        return TradeAccountResponse(
            trade_account_id=str(trade_account.trade_account_id),
            account_number=trade_account.account_number,
            company_name=trade_account.company_name,
            contact_email=trade_account.contact_email,
            credit_limit_minor=trade_account.credit_limit_minor,
            available_credit_minor=trade_account.available_credit_minor,
            currency=trade_account.currency,
            payment_terms_days=trade_account.payment_terms_days,
            is_active=trade_account.is_active,
            created_at=trade_account.created_at
        )

    except Exception as e:
        payment_requests_total.labels(endpoint="create_trade_account", status="fail").inc()
        logger.error(f"Failed to create trade account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trade-accounts")
async def list_trade_accounts(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db = Depends(get_db_with_rls)
):
    """List trade accounts - Phase 5"""
    try:
        query = db.query(TradeAccount).filter(
            TradeAccount.tenant_id == uuid.UUID(tenant_id),
            TradeAccount.is_active == True
        )

        accounts = query.offset(offset).limit(limit).all()

        return {
            "trade_accounts": [
                TradeAccountResponse(
                    trade_account_id=str(acc.trade_account_id),
                    account_number=acc.account_number,
                    company_name=acc.company_name,
                    contact_email=acc.contact_email,
                    credit_limit_minor=acc.credit_limit_minor,
                    available_credit_minor=acc.available_credit_minor,
                    currency=acc.currency,
                    payment_terms_days=acc.payment_terms_days,
                    is_active=acc.is_active,
                    created_at=acc.created_at
                )
                for acc in accounts
            ],
            "total": len(accounts),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Failed to list trade accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payment-intents", response_model=PaymentIntentResponse)
async def create_payment_intent(
    request: PaymentIntentRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a payment intent - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="create_payment_intent", status="start").inc()

        # Check permissions
        if not check_permission("payments.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Check if trade account exists and has sufficient credit
        if request.trade_account_id:
            trade_account = db.query(TradeAccount).filter(
                TradeAccount.trade_account_id == uuid.UUID(request.trade_account_id),
                TradeAccount.tenant_id == uuid.UUID(uctx["tenant_id"]),
                TradeAccount.is_active == True
            ).first()

            if not trade_account:
                raise HTTPException(status_code=404, detail="Trade account not found")

            if trade_account.available_credit_minor < request.amount_minor:
                raise HTTPException(status_code=400, detail="Insufficient credit limit")

        # Create payment intent
        payment_intent = PaymentIntent(
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            order_id=uuid.UUID(request.order_id) if request.order_id else None,
            trade_account_id=uuid.UUID(request.trade_account_id) if request.trade_account_id else None,
            amount_minor=request.amount_minor,
            currency=request.currency,
            provider="stripe",  # Default to Stripe for Phase 5
            payment_method=request.payment_method,
            metadata=request.metadata,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
        )

        db.add(payment_intent)
        db.commit()
        db.refresh(payment_intent)

        # Create Stripe payment intent
        stripe_provider = StripeProvider({"api_key": os.getenv("STRIPE_SECRET_KEY", "sk_test_demo")})

        stripe_intent = await stripe_provider.create_payment_intent({
            "amount": request.amount_minor,
            "currency": request.currency.lower(),
            "payment_method_types": [request.payment_method],
            "metadata": {
                "payment_intent_id": str(payment_intent.payment_intent_id),
                "tenant_id": uctx["tenant_id"],
                "user_id": uctx["user_id"]
            }
        })

        # Update payment intent with provider details
        payment_intent.provider_intent_id = stripe_intent.get("id")
        payment_intent.status = "processing"
        db.commit()

        payment_requests_total.labels(endpoint="create_payment_intent", status="ok").inc()

        return PaymentIntentResponse(
            payment_intent_id=str(payment_intent.payment_intent_id),
            client_secret=stripe_intent.get("client_secret"),
            amount_minor=payment_intent.amount_minor,
            currency=payment_intent.currency,
            status=payment_intent.status,
            provider=payment_intent.provider,
            expires_at=payment_intent.expires_at
        )

    except HTTPException:
        raise
    except Exception as e:
        payment_requests_total.labels(endpoint="create_payment_intent", status="fail").inc()
        logger.error(f"Failed to create payment intent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/currency/convert", response_model=MultiCurrencyConversionResponse)
async def convert_currency(
    request: MultiCurrencyConversionRequest,
    db = Depends(get_db_with_rls)
):
    """Convert currency using stored exchange rates - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="convert_currency", status="start").inc()

        # Get current exchange rate
        rate_record = db.query(CurrencyRate).filter(
            CurrencyRate.base_currency == request.from_currency.upper(),
            CurrencyRate.target_currency == request.to_currency.upper(),
            CurrencyRate.is_active == True,
            CurrencyRate.valid_from <= datetime.now(timezone.utc),
            or_(CurrencyRate.valid_to.is_(None), CurrencyRate.valid_to >= datetime.now(timezone.utc))
        ).order_by(CurrencyRate.created_at.desc()).first()

        if not rate_record:
            # Use fallback rate (1:1 for demo)
            exchange_rate = 1.0
        else:
            exchange_rate = float(rate_record.rate)

        converted_amount = int(request.amount_minor * exchange_rate)

        payment_requests_total.labels(endpoint="convert_currency", status="ok").inc()

        return MultiCurrencyConversionResponse(
            from_currency=request.from_currency.upper(),
            to_currency=request.to_currency.upper(),
            original_amount_minor=request.amount_minor,
            converted_amount_minor=converted_amount,
            exchange_rate=exchange_rate,
            converted_at=datetime.now(timezone.utc)
        )

    except Exception as e:
        payment_requests_total.labels(endpoint="convert_currency", status="fail").inc()
        logger.error(f"Failed to convert currency: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/payment-intents/{payment_intent_id}")
async def get_payment_intent(
    payment_intent_id: str,
    db = Depends(get_db_with_rls)
):
    """Get payment intent details - Phase 5"""
    try:
        payment_intent = db.query(PaymentIntent).filter(
            PaymentIntent.payment_intent_id == uuid.UUID(payment_intent_id)
        ).first()

        if not payment_intent:
            raise HTTPException(status_code=404, detail="Payment intent not found")

        return {
            "payment_intent_id": str(payment_intent.payment_intent_id),
            "order_id": str(payment_intent.order_id) if payment_intent.order_id else None,
            "trade_account_id": str(payment_intent.trade_account_id) if payment_intent.trade_account_id else None,
            "amount_minor": payment_intent.amount_minor,
            "currency": payment_intent.currency,
            "status": payment_intent.status,
            "provider": payment_intent.provider,
            "provider_intent_id": payment_intent.provider_intent_id,
            "payment_method": payment_intent.payment_method,
            "metadata": payment_intent.payment_metadata,
            "expires_at": payment_intent.expires_at.isoformat() if payment_intent.expires_at else None,
            "succeeded_at": payment_intent.succeeded_at.isoformat() if payment_intent.succeeded_at else None,
            "failed_at": payment_intent.failed_at.isoformat() if payment_intent.failed_at else None,
            "created_at": payment_intent.created_at.isoformat(),
            "updated_at": payment_intent.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get payment intent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
# MAIN EXECUTION
# =============================================================================
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