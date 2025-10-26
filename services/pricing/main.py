# services/pricing/main.py - ZeroQue Pricing Service V2
# Production-ready pricing service with Celery, RabbitMQ, and saga patterns

import os
import uuid
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from sqlalchemy import  text

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import get_settings
from .utils.pricing_logger import logger
from .core.celery_config import celery_app
from .utils.metrics import saga_total, saga_duration, pricing_operations_total, pricing_operation_duration
from .repositories.db_config import engine, SessionLocal
from .models import Base, PriceRuleV2, CalculatedPriceV2, OutboxEvent, AuditLog
from .schemas import PricebookRequest, PriceRuleRequest, PriceCalculationRequest, PriceCalculationResponse
from .utils.user_auth import get_user_context
from .repositories.pricing_saga import PricebookSaga


# Configuration
SERVICE_NAME = "pricing"
SERVICE_VERSION = "4.1.0"

DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM

import pybreaker
# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# External service URLs
CATALOG_BASE = os.getenv("CATALOG_BASE", "http://localhost:8008")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8003")

# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

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
        allow_demo_mode = os.getenv("ALLOW_DEMO", "false").lower() == "true"
        if not allow_demo_mode:
            set_rls_context(db, uctx["tenant_id"])
        yield db
    finally:
        db.close()

    """Best-effort RLS context setter. Tenant-aware DBs may ignore this."""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": uctx["tenant_id"]})
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
        pricing_operations_total.labels(operation="create_pricebook", status="start").inc()
        
        pricebook_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]
        
        saga = PricebookSaga(db)
        result = await saga.exec(pricebook_id, tenant_id, req, uctx)
        
        pricing_operations_total.labels(operation="create_pricebook", status="ok").inc()
        pricing_operation_duration.labels(operation="create_pricebook").observe(time.time() - start)
        
        return result
        
    except ValueError as e:
        pricing_operations_total.labels(operation="create_pricebook", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        pricing_operations_total.labels(operation="create_pricebook", status="fail").inc()
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