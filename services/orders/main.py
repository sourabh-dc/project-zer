# services/orders/main.py
"""
Enhanced Orders Service with V2 Multi-Tenant Marketplace Architecture

This service implements:
- Full Celery integration with service bus and events
- Saga pattern for distributed order transactions
- Circuit breaker pattern for external service calls
- Event sourcing and health monitoring
- V2 architecture with new tables and models
"""

import os
import sys
import asyncio
import logging
import uuid
import requests
from fastapi import FastAPI, Body, HTTPException, Query, Path, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime, timezone
from sqlalchemy import text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError

# Add the packages path to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'packages', 'zeroque_common'))

from zeroque_common.communication import (
    ServiceBus, ServiceEvent, ServiceEventType,
    CircuitBreaker, CircuitBreakerConfig,
    SagaOrchestrator, SagaStep,
    ServiceRegistry, HealthMonitor,
    EventStore,
    # Global instances
    service_bus as global_service_bus,
    service_circuit_breaker,
    saga_orchestrator,
    service_registry,
    health_monitor,
    event_store
)
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.billing.helpers import create_trade_invoice_if_applicable
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.events.integration import publish_order_created, publish_order_completed
from zeroque_common.events.bus import EventBus, EventType, Event
from zeroque_common.events.celery_app import celery_app
from zeroque_common.observability import setup_logging, init_metrics, init_insights, add_observability_middleware

# Custom Exceptions
class OrderValidationError(Exception):
    """Raised when order validation fails"""
    pass

class OrderNotFoundError(Exception):
    """Raised when order is not found"""
    pass

class OrderDuplicateError(Exception):
    """Raised when duplicate order is created"""
    pass

class OrderProcessingError(Exception):
    """Raised when order processing fails"""
    pass

class PaymentProcessingError(Exception):
    """Raised when payment processing fails"""
    pass

# Service configuration
SERVICE_NAME = "orders"
app = FastAPI(title="Enhanced ZeroQue Orders Service", version="2.0.0")

# Initialize enhanced communication
service_bus = global_service_bus
circuit_breaker_config = CircuitBreakerConfig(
    failure_threshold=3,
    timeout=30,
    success_threshold=2
)

# ---- observability ----
logger = setup_logging(SERVICE_NAME, "2.0.0")
metrics = init_metrics(SERVICE_NAME)
insights = init_insights(SERVICE_NAME, "2.0.0")

# ---- middleware ----
add_observability_middleware(app, SERVICE_NAME)
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[("POST", "/orders"), ("POST", "/orders/v2")])

# Custom exception handlers
@app.exception_handler(OrderValidationError)
async def order_validation_exception_handler(request, exc: OrderValidationError):
    """Handle order validation errors"""
    logger.warning(f"Order validation error: {exc}")
    return HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(OrderNotFoundError)
async def order_not_found_exception_handler(request, exc: OrderNotFoundError):
    """Handle order not found errors"""
    logger.warning(f"Order not found error: {exc}")
    return HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(OrderDuplicateError)
async def order_duplicate_exception_handler(request, exc: OrderDuplicateError):
    """Handle order duplicate errors"""
    logger.warning(f"Order duplicate error: {exc}")
    return HTTPException(status_code=409, detail=str(exc))

@app.exception_handler(OrderProcessingError)
async def order_processing_exception_handler(request, exc: OrderProcessingError):
    """Handle order processing errors"""
    logger.error(f"Order processing error: {exc}")
    return HTTPException(status_code=500, detail=str(exc))

@app.exception_handler(PaymentProcessingError)
async def payment_processing_exception_handler(request, exc: PaymentProcessingError):
    """Handle payment processing errors"""
    logger.error(f"Payment processing error: {exc}")
    return HTTPException(status_code=500, detail=str(exc))

# ---- config ----
PAYMENTS_BASE = os.getenv("PAYMENTS_BASE", "http://localhost:8216")
BILLING_BASE  = os.getenv("BILLING_BASE",  "http://localhost:8206")
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8209")
INVENTORY_BASE = os.getenv("INVENTORY_BASE", "http://localhost:8202")

# ---- event bus ----
event_bus = EventBus()

# Try to use uuid7 for time-sortable UUIDs, fallback to uuid4 if not available
try:
    from uuid6 import uuid7  # python-uuid7/uuid6 lib; or your util
except Exception:
    from uuid import uuid4 as uuid7

def generate_time_sortable_uuid():
    u = uuid7()
    return u if isinstance(u, uuid.UUID) else uuid.UUID(str(u))

# ---- V2 SQLAlchemy Models ----
Base = declarative_base()

class OrderV2(Base):
    __tablename__ = "orders_new"
    
    order_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_time_sortable_uuid)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    total_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="GBP")
    payment_method = Column(String(20), nullable=True)
    payment_status = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

class SubOrderV2(Base):
    __tablename__ = "sub_orders"
    
    sub_order_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_time_sortable_uuid)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders_new.order_id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    total_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="GBP")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

class OrderItemV2(Base):
    __tablename__ = "order_items_new"
    
    item_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_time_sortable_uuid)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders_new.order_id"), nullable=False)
    sub_order_id = Column(UUID(as_uuid=True), ForeignKey("sub_orders.sub_order_id"), nullable=True)
    offer_id = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    total_price_minor = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class ReturnV2(Base):
    __tablename__ = "returns"
    
    return_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_time_sortable_uuid)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders_new.order_id"), nullable=False)
    reason = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    total_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="GBP")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

class RefundV2(Base):
    __tablename__ = "refunds"
    
    refund_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_time_sortable_uuid)
    return_id = Column(UUID(as_uuid=True), ForeignKey("returns.return_id"), nullable=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders_new.order_id"), nullable=False)
    amount_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="GBP")
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

# Database Transaction Helper
def execute_with_rollback(db_session, operation_name: str = "database operation"):
    """Context manager for database operations with proper rollback handling"""
    class DatabaseTransaction:
        def __init__(self, session, name):
            self.session = session
            self.name = name
            self.committed = False
            
        def __enter__(self):
            return self.session
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is not None:
                try:
                    self.session.rollback()
                    logger.error(f"Database transaction rolled back for {self.name}: {exc_val}")
                except Exception as rollback_error:
                    logger.error(f"Failed to rollback transaction for {self.name}: {rollback_error}")
                return False  # Re-raise the original exception
            else:
                try:
                    self.session.commit()
                    self.committed = True
                    logger.debug(f"Database transaction committed for {self.name}")
                except Exception as commit_error:
                    self.session.rollback()
                    logger.error(f"Failed to commit transaction for {self.name}: {commit_error}")
                    raise
            return True
    
    return DatabaseTransaction(db_session, operation_name)

# Validation Helpers
def validate_uuid(uuid_string: str, field_name: str = "UUID"):
    """Validate UUID format"""
    try:
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        raise OrderValidationError(f"Invalid {field_name} format: {uuid_string}")

def validate_references_exist(db_session, references: Dict[str, str]):
    """Validate that referenced entities exist"""
    for entity_type, entity_id in references.items():
        if entity_type == "tenant_id":
            # Check if tenant exists in tenants_new table
            result = db_session.execute(text("SELECT 1 FROM tenants_new WHERE tenant_id = :tenant_id"), {"tenant_id": entity_id}).fetchone()
            if not result:
                raise OrderValidationError(f"Tenant {entity_id} does not exist")
        elif entity_type == "store_id":
            # Check if store exists
            result = db_session.execute(text("SELECT 1 FROM stores WHERE store_id = :store_id"), {"store_id": entity_id}).fetchone()
            if not result:
                raise OrderValidationError(f"Store {entity_id} does not exist")
        elif entity_type == "customer_id":
            # Check if user exists
            result = db_session.execute(text("SELECT 1 FROM users WHERE user_id = :user_id"), {"user_id": entity_id}).fetchone()
            if not result:
                raise OrderValidationError(f"Customer {entity_id} does not exist")

# ---- RLS Context Helper ----
def set_rls_context(db, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": user_id})
        
        # Enable RLS for the session
        db.execute(text("SET row_security = on"))
        
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set security context")

# ---- lifecycle ----
@app.on_event("startup")
async def startup():
    """Initialize enhanced service"""
    logger.info(f"Starting enhanced {SERVICE_NAME} service")
    
    # Initialize database
    get_engine()
    init_db()
    
    # Register service
    await service_registry.register_service(
        service_name=SERVICE_NAME,
        instance_id=f"{SERVICE_NAME}-{os.getpid()}",
        host="localhost",
        port=8208,
        metadata={"version": "2.0.0", "enhanced": True}
    )
    
    # Subscribe to events
    service_bus.subscribe_to_event(ServiceEventType.INVENTORY_UPDATED, handle_inventory_update)
    service_bus.subscribe_to_event(ServiceEventType.PRICE_CALCULATED, handle_price_calculation)
    service_bus.subscribe_to_event(ServiceEventType.PAYMENT_PROCESSED, handle_payment_processed)
    
    # Start event consumer
    await service_bus.start_consumer()
    
    # Start health monitoring
    await health_monitor.start_monitoring()
    
    # Publish service started event
    await service_bus.publish_to_service(
        target_service="observability",
        event_type=ServiceEventType.SERVICE_STARTED,
        data={
            "service_name": SERVICE_NAME,
            "version": "2.0.0",
            "startup_time": datetime.now(timezone.utc).isoformat(),
            "enhanced_features": ["saga", "circuit_breaker", "event_sourcing"]
        }
    )

# ---- Event Handlers ----
async def handle_inventory_update(event: ServiceEvent):
    """Handle inventory update events"""
    logger.info(f"Received inventory update: {event.data}")
    metrics.counter("event.inventory_update.received").inc()
    
    # Update order status if inventory affects order fulfillment
    if event.data.get("order_id"):
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=event.data.get("tenant_id"))
            db.execute(text("""
                UPDATE orders_new SET status='inventory_updated' 
                WHERE order_id=:oid AND status IN ('pending', 'created')
            """), {"oid": event.data.get("order_id")})
            db.commit()

async def handle_price_calculation(event: ServiceEvent):
    """Handle price calculation events"""
    logger.info(f"Received price calculation: {event.data}")
    metrics.counter("event.price_calculation.received").inc()
    
    # Update order with calculated pricing if needed
    if event.data.get("order_id"):
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=event.data.get("tenant_id"))
            db.execute(text("""
                UPDATE orders_new SET total_minor=:total, currency=:currency 
                WHERE order_id=:oid
            """), {
                "oid": event.data.get("order_id"),
                "total": event.data.get("total_minor"),
                "currency": event.data.get("currency")
            })
            db.commit()

async def handle_payment_processed(event: ServiceEvent):
    """Handle payment processed events"""
    logger.info(f"Received payment processed: {event.data}")
    metrics.counter("event.payment_processed.received").inc()
    
    # Update order status when payment is completed
    if event.data.get("order_id"):
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=event.data.get("tenant_id"))
            db.execute(text("""
                UPDATE orders_new SET payment_status='completed', status='completed' 
                WHERE order_id=:oid
            """), {"oid": event.data.get("order_id")})
            db.commit()
    # Update order payment status

# ---- Health Endpoints ----
@app.get("/health")
async def health():
    """Enhanced service health check"""
    try:
        service_health = await health_monitor.check_service_health(SERVICE_NAME)
        
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": "2.0.0",
            "enhanced": True,
            "overall_status": service_health.overall_status.value,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status.value,
                    "message": check.message,
                    "response_time_ms": check.response_time_ms
                }
                for check in service_health.checks
            ],
            "circuit_breakers": service_circuit_breaker.get_all_states(),
            "event_metrics": service_bus.get_service_metrics()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "error", "service": SERVICE_NAME, "error": str(e)}

@app.get("/readiness")
def readiness(): 
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# Observability endpoints
@app.get("/metrics")
def get_metrics():
    """Get service metrics"""
    return metrics.get_metrics_summary()

@app.get("/insights")
def get_service_insights():
    """Get service insights"""
    service_insights = insights.get_insights()
    return {
        "service_name": service_insights.service_name,
        "timestamp": service_insights.timestamp.isoformat(),
        "health_status": service_insights.health_status,
        "performance_metrics": service_insights.performance_metrics,
        "business_metrics": service_insights.business_metrics,
        "error_rate": service_insights.error_rate,
        "uptime_seconds": service_insights.uptime_seconds,
        "version": service_insights.version,
        "environment": service_insights.environment
    }

@app.get("/health/detailed")
def get_detailed_health():
    """Get detailed health status"""
    return insights.get_health_summary()

# ---- V2 Pydantic Models ----
class OrderItemV2Payload(BaseModel):
    offer_id: str
    quantity: int

class CreateOrderV2Request(BaseModel):
    tenant_id: str
    site_id: Optional[str] = None
    store_id: str  # required for cashierless flows
    customer_id: str
    currency: str = "GBP"
    items: List[OrderItemV2Payload]
    payment_method: str = "trade"
    idempotency_key: Optional[str] = None  # For preventing double-tap

class OrderV2Response(BaseModel):
    order_id: str
    status: str
    total_minor: int
    currency: str
    created_at: datetime
    saga_id: Optional[str] = None

class SubOrderV2Payload(BaseModel):
    order_id: str
    vendor_id: str
    total_minor: int
    currency: str = "GBP"

class ReturnV2Payload(BaseModel):
    order_id: str
    reason: str
    total_minor: int
    currency: str = "GBP"

class RefundV2Payload(BaseModel):
    return_id: Optional[str] = None
    order_id: str
    amount_minor: int
    currency: str = "GBP"

# ---- Legacy Models (for backward compatibility) ----
class NewOrderItem(BaseModel):
    sku: str
    qty: int

class NewOrder(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    shopper_id: str
    currency: str = "GBP"
    items: List[NewOrderItem]
    payment_method: Optional[Literal["stripe","trade"]] = None

# ---- OrderSaga Implementation ----
class OrderSaga:
    """Saga for managing order creation across multiple services"""
    
    def __init__(self):
        self.saga_orchestrator = SagaOrchestrator()
        self.steps = [
            SagaStep("validate_inventory", self.validate_inventory, self.compensate_inventory),
            SagaStep("validate_budget", self.validate_budget, None),
            SagaStep("calculate_pricing", self.calculate_pricing, self.compensate_pricing),
            SagaStep("reserve_inventory", self.reserve_inventory, self.release_inventory),
            SagaStep("process_payment", self.process_payment, self.refund_payment),
            SagaStep("create_order", self.create_order_record, self.delete_order_record),
            SagaStep("commit_inventory", self.commit_inventory, self.release_inventory),
            SagaStep("complete_order", self.complete_order, None),
            SagaStep("send_notification", self.send_notification, None)
        ]
    
    async def execute_order_saga(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the complete order saga"""
        saga_id = f"order_{int(datetime.now(timezone.utc).timestamp())}"
        
        try:
            result = await self.saga_orchestrator.execute_saga(
                saga_id=saga_id,
                steps=self.steps,
                initial_data=order_data
            )
            
            # Publish order completed event
            await service_bus.publish_to_service(
                target_service="billing",
                event_type=ServiceEventType.ORDER_COMPLETED,
                data={
                    "order_id": result["order_id"],
                    "total_minor": result["total_minor"],
                    "currency": result["currency"],
                    "saga_id": saga_id
                },
                correlation_id=saga_id
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Order saga {saga_id} failed: {str(e)}")
            metrics.counter("saga.order.failed").inc()
            raise
    
    async def validate_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate inventory availability"""
        logger.info(f"Validating inventory for order: {data}")
        metrics.counter("saga.validate_inventory.started").inc()
        
        try:
            response = await service_circuit_breaker.call_service(
                service_name="inventory",
                url=f"{INVENTORY_BASE}/inventory/v2/validate",
                payload={
                    "store_id": data["store_id"],
                    "items": [{"offer_id": item["offer_id"], "quantity": item["quantity"]} for item in data["items"]]
                },
                config=circuit_breaker_config
            )
            
            if not response.get("valid", False):
                raise HTTPException(status_code=400, detail="Insufficient inventory")
            
            metrics.counter("saga.validate_inventory.completed").inc()
            return {"inventory_validated": True}
            
        except Exception as e:
            logger.warning(f"Inventory validation failed (using fallback): {str(e)}")
            # For now, assume inventory is available if service is not reachable
            # In production, this should be handled more carefully
            metrics.counter("saga.validate_inventory.fallback").inc()
            return {"inventory_validated": True, "fallback": True}
    
    async def validate_budget(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate budget and approvals for the order"""
        logger.info(f"Validating budget for order: {data}")
        metrics.counter("saga.validate_budget.started").inc()
        
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=data["tenant_id"], user_id=data["customer_id"])
            cc_id = _user_cc(db, data["customer_id"])
            if not cc_id:
                raise HTTPException(400, "Customer has no cost centre")
            
            snap = _budget_snapshot(db, cc_id)
            if not snap:
                raise HTTPException(400, "No budget configured")
            
            remaining = snap["limit_minor"] - snap["spent_minor"]
            if data["total_minor"] > remaining:
                covered = _approval_cover_and_consume(db, cc_id, data["customer_id"], data["total_minor"] - remaining)
                if not covered:
                    raise HTTPException(403, "Budget overspend; no approval cover")
            
            db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                       {"amt": data["total_minor"], "cc": cc_id})
            db.commit()
        
        metrics.counter("saga.validate_budget.completed").inc()
        return {"budget_validated": True}
    
    async def calculate_pricing(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate pricing for order items"""
        logger.info(f"Calculating pricing for order: {data}")
        metrics.counter("saga.calculate_pricing.started").inc()
        
        pricing_data = {"items": [], "total_minor": 0, "currency": data["currency"]}
        
        for item in data["items"]:
            try:
                response = await service_circuit_breaker.call_service(
                    service_name="pricing",
                    url=f"{PRICING_BASE}/pricing/v2/resolve",
                    payload={
                        "store_id": data["store_id"],
                        "offer_id": item["offer_id"],
                        "user_id": data["customer_id"],
                        "site_id": data.get("site_id"),
                        "tenant_id": data.get("tenant_id"),
                        "currency": data["currency"],
                        "quantity": item["quantity"]
                    },
                    config=circuit_breaker_config
                )
                
                item_total = response["final_price_minor"] * item["quantity"]
                pricing_data["items"].append({
                    "offer_id": item["offer_id"],
                    "quantity": item["quantity"],
                    "unit_price_minor": response["final_price_minor"],
                    "total_minor": item_total
                })
                pricing_data["total_minor"] += item_total
                
            except Exception as e:
                logger.error(f"Pricing calculation failed for {item['offer_id']}: {str(e)}")
                # Fallback to default pricing
                default_price = 1000  # Default price in minor units
                item_total = default_price * item["quantity"]
                pricing_data["items"].append({
                    "offer_id": item["offer_id"],
                    "quantity": item["quantity"],
                    "unit_price_minor": default_price,
                    "total_minor": item_total
                })
                pricing_data["total_minor"] += item_total
        
        metrics.counter("saga.calculate_pricing.completed").inc()
        return {**data, **pricing_data}  # carry forward to next saga step
    
    async def reserve_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Reserve inventory for the order"""
        logger.info(f"Reserving inventory for order: {data}")
        metrics.counter("saga.reserve_inventory.started").inc()
        
        try:
            # Call Inventory service synchronously to get reservation ID + TTL
            response = await service_circuit_breaker.call_service(
                service_name="inventory",
                url=f"{INVENTORY_BASE}/inventory/v2/reserve",
                payload={
                    "store_id": data["store_id"],
                    "items": [{"offer_id": item["offer_id"], "quantity": item["quantity"]} for item in data["items"]],
                    "order_id": data.get("order_id", "pending"),
                    "ttl_minutes": 30  # 30 minute reservation
                },
                config=circuit_breaker_config
            )
            
            reservation_id = response.get("reservation_id")
            ttl_seconds = response.get("ttl_seconds", 1800)  # 30 minutes default
            
            if not reservation_id:
                raise HTTPException(status_code=400, detail="Failed to reserve inventory")
            
            # Store reservation in order data for compensation
            data["reservation_id"] = reservation_id
            data["reservation_ttl"] = ttl_seconds
            
            metrics.counter("saga.reserve_inventory.completed").inc()
            return {"inventory_reserved": True, "reservation_id": reservation_id}
            
        except Exception as e:
            logger.warning(f"Inventory reservation failed (using fallback): {str(e)}")
            # For now, create a mock reservation ID if service is not reachable
            mock_reservation_id = f"mock_reservation_{int(datetime.now(timezone.utc).timestamp())}"
            data["reservation_id"] = mock_reservation_id
            data["reservation_ttl"] = 1800
            
            metrics.counter("saga.reserve_inventory.fallback").inc()
            return {"inventory_reserved": True, "reservation_id": mock_reservation_id, "fallback": True}
    
    async def process_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process payment for the order"""
        logger.info(f"Processing payment for order: {data}")
        metrics.counter("saga.process_payment.started").inc()
        
        payment_method = data.get("payment_method", "trade")
        
        if payment_method == "trade":
            # For trade orders, just mark as processed
            metrics.counter("saga.process_payment.completed").inc()
            return {"payment_processed": True, "payment_method": "trade", "status": "completed"}
        
        # For non-trade methods, call Payments service
        try:
            response = await service_circuit_breaker.call_service(
                service_name="payments",
                url=f"{PAYMENTS_BASE}/payments/v2/intents",
                payload={
                    "tenant_id": data["tenant_id"],
                    "order_id": data.get("order_id", "pending"),
                    "amount_minor": data["total_minor"],
                    "currency": data["currency"],
                    "payment_method": payment_method,
                    "site_id": data.get("site_id"),
                    "store_id": data["store_id"]
                },
                config=circuit_breaker_config
            )
            
            intent_id = response.get("intent_id")
            payment_status = response.get("status", "pending")
            
            if not intent_id:
                raise HTTPException(status_code=400, detail="Failed to create payment intent")
            
            # Store payment intent for later completion
            data["payment_intent_id"] = intent_id
            data["payment_status"] = payment_status
            
            metrics.counter("saga.process_payment.completed").inc()
            return {
                "payment_processed": True, 
                "payment_method": payment_method,
                "intent_id": intent_id,
                "status": payment_status
            }
            
        except Exception as e:
            logger.error(f"Payment processing failed: {str(e)}")
            metrics.counter("saga.process_payment.failed").inc()
            raise
    
    async def create_order_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create the order record in the database with sub-orders and vendor splits"""
        logger.info(f"Creating order record: {data}")
        metrics.counter("saga.create_order.started").inc()
        
        order_id = generate_time_sortable_uuid()
        
        # Store in database
        db = SessionLocal()
        try:
            set_rls_context(db, tenant_id=data["tenant_id"], user_id=data["customer_id"])
            
            # Determine initial status based on payment method
            initial_status = "created" if data.get("payment_method") == "trade" else "payment_pending"
            
            # Create main order with initial status
            order_number = f"ORD-{int(datetime.now(timezone.utc).timestamp())}"
            db.execute(text("""
                   INSERT INTO orders_new(order_id, order_number, tenant_id, site_id, store_id, customer_id, 
                                       total_minor, currency, payment_method, payment_status, status, created_at)
                   VALUES(:order_id, :order_number, :tenant_id, :site_id, :store_id, :customer_id, 
                          :total_minor, :currency, :payment_method, :payment_status, :status, NOW())
               """), {
                   "order_id": order_id,
                   "order_number": order_number,
                   "tenant_id": data["tenant_id"],
                   "site_id": data["site_id"],
                   "store_id": data["store_id"],
                   "customer_id": data["customer_id"],
                "total_minor": data["total_minor"],
                "currency": data["currency"],
                "payment_method": data.get("payment_method", "trade"),
                "payment_status": data.get("payment_status"),
                "status": initial_status
            })
            
            # 1) Fetch vendor per offer
            offer_ids = [item["offer_id"] for item in data["items"]]
            # Convert string offer_ids to UUID objects for proper comparison
            offer_uuids = [str(offer_id) for offer_id in offer_ids]
            offer_rows = db.execute(text("""
                SELECT vo.vendor_id, vo.offer_id
                  FROM vendor_offers vo
                 WHERE vo.offer_id::text = ANY(:offer_ids)
            """), {"offer_ids": offer_uuids}).all()
            offer_to_vendor = {str(r[1]): str(r[0]) for r in offer_rows}
            
            # 2) Group items by vendor
            vendor_items: Dict[str, list] = {}
            for item in data["items"]:
                vendor_id = offer_to_vendor.get(item["offer_id"])
                if not vendor_id:
                    raise HTTPException(400, f"Unknown vendor for offer {item['offer_id']}")
                vendor_items.setdefault(vendor_id, []).append(item)
            
            # 3) Create sub-orders and attach items
            sub_ids = {}
            for vendor_id, items in vendor_items.items():
                sub_id = generate_time_sortable_uuid()
                sub_total = sum(int(item["total_minor"]) for item in items)
                sub_order_number = f"SUB-{int(datetime.now(timezone.utc).timestamp())}-{vendor_id[:8]}"
                db.execute(text("""
                    INSERT INTO sub_orders(sub_order_id, order_id, vendor_id, sub_order_number, status, total_amount_minor, created_at)
                    VALUES(:sid, :oid, :vid, :sub_num, 'pending', :tot, NOW())
                """), {"sid": sub_id, "oid": order_id, "vid": vendor_id, "sub_num": sub_order_number, "tot": sub_total})
                sub_ids[vendor_id] = sub_id
                
                # Create vendor splits with commission calculation
                # For now, use a default commission rate of 5% (500 basis points)
                # In production, this should come from a commissions table or vendor configuration
                default_commission_bp = 500  # 5%
                commission_minor = sub_total * default_commission_bp // 10000
                payout_minor = sub_total - commission_minor
                
                # TODO: Create order_vendor_splits table in migration
                # db.execute(text("""
                #     INSERT INTO order_vendor_splits(order_id, vendor_id, subtotal_minor, commission_minor, vendor_payout_minor, currency, payout_status, created_at)
                #     VALUES(:o,:v,:sub,:com,:pay,:cur,'pending',NOW())
                # """), {"o": order_id, "v": vendor_id, "sub": sub_total, "com": commission_minor, "pay": payout_minor, "cur": data["currency"]})
            
            # 4) Create order items with sub_order_id
            for item in data["items"]:
                vendor_id = offer_to_vendor[item["offer_id"]]
                sub_order_id = sub_ids[vendor_id]
                
                # Get product details from vendor_offers
                product_info = db.execute(text("""
                    SELECT vo.vendor_sku, vo.vendor_product_name
                    FROM vendor_offers vo
                    WHERE vo.offer_id::text = :offer_id
                """), {"offer_id": item["offer_id"]}).first()
                
                if not product_info:
                    raise HTTPException(400, f"Product info not found for offer {item['offer_id']}")
                
                item_id = generate_time_sortable_uuid()
                db.execute(text("""
                    INSERT INTO order_items(item_id, order_id, sub_order_id, offer_id, quantity, unit_price_minor, total_price_minor)
                    VALUES(:item_id, :order_id, :sub_order_id, :offer_id, :quantity, :unit_price_minor, :total_price_minor)
                """), {
                    "item_id": item_id,
                    "order_id": order_id,
                    "sub_order_id": sub_order_id,
                    "offer_id": item["offer_id"],
                    "quantity": item["quantity"],
                    "unit_price_minor": item["unit_price_minor"],
                    "total_price_minor": item["total_minor"]
                })
            
            # Apply inventory decrements
            _apply_inventory_decrements(db, data["store_id"], [
                {"sku": db.execute(text("SELECT vendor_sku FROM vendor_offers WHERE offer_id::text = :oid"), 
                                  {"oid": item["offer_id"]}).scalar() or item["offer_id"], 
                 "qty": item["quantity"]} for item in data["items"]
            ])
            
            # Create ledger entries for budget tracking
            cc_id = _user_cc(db, data["customer_id"])
            if cc_id:
                db.execute(text("""
                    INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                                  cost_centre_id, site_id, store_id,
                                                  reference_type, reference_id, description)
                    VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:s,:st,'order',:ref,'Orders V2')
                """), {"t": data["tenant_id"], "amt": data["total_minor"], "cur": data["currency"], 
                       "cc": cc_id, "s": data["site_id"], "st": data["store_id"], "ref": order_id})
                db.execute(text("""
                    INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                                  cost_centre_id, site_id, store_id,
                                                  reference_type, reference_id, description)
                    VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:s,:st,'order',:ref,'Orders V2')
                """), {"t": data["tenant_id"], "amt": data["total_minor"], "cur": data["currency"], 
                       "cc": cc_id, "s": data["site_id"], "st": data["store_id"], "ref": order_id})
            
            db.commit()
            
            metrics.counter("saga.create_order.completed").inc()
            return {
                "order_id": str(order_id), 
                "order_created": True,
                "total_minor": data["total_minor"],
                "currency": data["currency"],
                "status": initial_status
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create order record: {str(e)}")
            metrics.counter("saga.create_order.failed").inc()
            raise
        finally:
            db.close()
    
    async def commit_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Commit reserved inventory"""
        logger.info(f"Committing inventory for order: {data}")
        metrics.counter("saga.commit_inventory.started").inc()
        
        try:
            # Call Inventory service to commit the reservation
            response = await service_circuit_breaker.call_service(
                service_name="inventory",
                url=f"{INVENTORY_BASE}/inventory/v2/commit",
                payload={
                    "reservation_id": data.get("reservation_id"),
                    "order_id": data.get("order_id")
                },
                config=circuit_breaker_config
            )
            
            if not response.get("committed", False):
                raise HTTPException(status_code=400, detail="Failed to commit inventory")
            
            metrics.counter("saga.commit_inventory.completed").inc()
            return {"inventory_committed": True}
            
        except Exception as e:
            logger.warning(f"Inventory commit failed (using fallback): {str(e)}")
            # For now, assume inventory is committed if service is not reachable
            metrics.counter("saga.commit_inventory.fallback").inc()
            return {"inventory_committed": True, "fallback": True}
    
    async def complete_order(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Complete the order by updating status"""
        logger.info(f"Completing order: {data}")
        metrics.counter("saga.complete_order.started").inc()
        
        db = SessionLocal()
        try:
            set_rls_context(db, tenant_id=data["tenant_id"], user_id=data["customer_id"])
            
            # Update order status to completed
            db.execute(text("""
                UPDATE orders_new 
                SET status='completed', updated_at=NOW() 
                WHERE order_id=:order_id
            """), {"order_id": data["order_id"]})
            
            # Update sub-orders status
            db.execute(text("""
                UPDATE sub_orders 
                SET status='completed', updated_at=NOW() 
                WHERE order_id=:order_id
            """), {"order_id": data["order_id"]})
            
            db.commit()
            
            metrics.counter("saga.complete_order.completed").inc()
            return {"order_completed": True}
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to complete order: {str(e)}")
            metrics.counter("saga.complete_order.failed").inc()
            raise
        finally:
            db.close()
    
    async def send_notification(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send order notification"""
        logger.info(f"Sending notification for order: {data}")
        metrics.counter("saga.send_notification.started").inc()
        
        # Publish notification event
        await service_bus.publish_to_service(
            target_service="notifications",
            event_type=ServiceEventType.ORDER_CREATED,
            data={
                "order_id": data["order_id"],
                "customer_id": data["customer_id"],
                "total_minor": data["total_minor"],
                "currency": data["currency"]
            },
            correlation_id=data.get("saga_id", "")
        )
        
        metrics.counter("saga.send_notification.completed").inc()
        return {"notification_sent": True}
    
    # Compensation methods
    async def compensate_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate inventory validation"""
        logger.info(f"Compensating inventory validation: {data}")
        metrics.counter("saga.compensate_inventory.executed").inc()
        return {}
    
    async def compensate_pricing(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate pricing calculation"""
        logger.info(f"Compensating pricing calculation: {data}")
        metrics.counter("saga.compensate_pricing.executed").inc()
        return {}
    
    async def release_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Release reserved inventory"""
        logger.info(f"Releasing inventory: {data}")
        metrics.counter("saga.release_inventory.executed").inc()
        
        try:
            # Call Inventory service to release the reservation
            if data.get("reservation_id"):
                await service_circuit_breaker.call_service(
                    service_name="inventory",
                    url=f"{INVENTORY_BASE}/inventory/v2/release",
                    payload={
                        "reservation_id": data["reservation_id"],
                        "reason": "order_failed"
                    },
                    config=circuit_breaker_config
                )
            else:
                # Fallback to event-based release
                await service_bus.publish_to_service(
                    target_service="inventory",
                    event_type=ServiceEventType.INVENTORY_RELEASED,
                    data={
                        "store_id": data.get("store_id"),
                        "items": data.get("items", []),
                        "reason": "order_failed"
                    },
                    correlation_id=data.get("saga_id", "")
                )
            
            return {"inventory_released": True}
            
        except Exception as e:
            logger.error(f"Failed to release inventory: {str(e)}")
            return {"inventory_released": False, "error": str(e)}
    
    async def refund_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Refund payment"""
        logger.info(f"Refunding payment: {data}")
        metrics.counter("saga.refund_payment.executed").inc()
        return {"payment_refunded": True}
    
    async def delete_order_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Delete order record"""
        logger.info(f"Deleting order record: {data}")
        metrics.counter("saga.delete_order_record.executed").inc()
        return {"order_deleted": True}

# Initialize saga
order_saga = OrderSaga()

# ---- helpers ----
def _user_cc(db, user_id: str) -> Optional[str]:
    row = db.execute(
        text("""SELECT cost_centre_id
                  FROM user_cost_centres
                 WHERE user_id=:u
              ORDER BY id ASC LIMIT 1"""),
        {"u": user_id}
    ).first()
    return row[0] if row else None

def _budget_snapshot(db, cc_id: str):
    row = db.execute(text("""
        SELECT limit_minor, spent_minor, currency, hard_block
          FROM budgets
         WHERE cost_centre_id=:cc
         ORDER BY budget_id DESC
         LIMIT 1
    """), {"cc": cc_id}).first()
    if not row:
        return None
    return {
        "limit_minor": int(row[0]),
        "spent_minor": int(row[1]),
        "currency": row[2],
        "hard_block": bool(row[3]),
    }

def _update_daily(db, when: datetime, tenant_id: str, site_id: Optional[str], store_id: Optional[str], meter_code: str, delta: int):
    """Upsert into daily usage aggregate; resilient to races."""
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
            db.execute(text("""
                UPDATE usage_aggregates_daily
                   SET value = value + :delta
                 WHERE day=:d AND tenant_id=:t
                   AND COALESCE(site_id,'')=COALESCE(:s,'')
                   AND COALESCE(store_id,'')=COALESCE(:st,'')
                   AND meter_code = :m
            """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code})

def _approval_cover_and_consume(db, cost_centre_id: str, user_id: str, amount: int) -> bool:
    """Consume from approvals (user-scoped first, then CC-wide) to cover 'amount' of overspend."""
    need = amount
    for scoped in (True, False):
        rows = db.execute(text("""
            SELECT id, remaining_minor
              FROM approval_requests
             WHERE cost_centre_id=:cc AND status='approved'
               AND (:u IS NULL OR (user_scope_id = :u))
               AND (:scoped = TRUE AND user_scope_id IS NOT NULL OR :scoped = FALSE AND user_scope_id IS NULL)
             ORDER BY approved_at DESC NULLS LAST, id DESC
        """), {"cc": cost_centre_id, "u": user_id, "scoped": scoped}).all()
        for r in rows:
            if need <= 0: break
            ar_id, rem = int(r[0]), int(r[1] or 0)
            if rem <= 0: continue
            take = min(rem, need)
            db.execute(text("""
                UPDATE approval_requests
                   SET remaining_minor = remaining_minor - :take
                 WHERE id=:id
            """), {"take": take, "id": ar_id})
            need -= take
    return need == 0

def _apply_inventory_decrements(db, store_id: str, items: list[dict]):
    """Decrement inventory and append 'sale' movements."""
    for it in items:
        sku = it["sku"]; q = int(it["qty"])
        upd = db.execute(text("""
            UPDATE inventory SET qty = qty - :q WHERE store_id=:st AND sku=:s
        """), {"q": q, "st": store_id, "s": sku}).rowcount
        if upd == 0:
            db.execute(text("""
                INSERT INTO inventory(store_id, sku, qty) VALUES(:st, :s, :q)
            """), {"st": store_id, "s": sku, "q": -q})
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason)
            VALUES(:st, :s, :d, 'sale')
        """), {"st": store_id, "s": sku, "d": -q})

# ---- V2 Endpoints ----
@app.post("/orders/v2", response_model=OrderV2Response)
async def create_order_v2(request: CreateOrderV2Request = Body(...)):
    """Create order with enhanced V2 architecture and saga pattern"""
    start_time = datetime.now()
    metrics.counter("endpoint.create_order_v2.called").inc()
    
    correlation_id = f"order_{datetime.now().isoformat()}"
    
    try:
        # Validate currency against currencies table
        with SessionLocal() as db:
            currency_valid = db.execute(text("""
                SELECT 1 FROM currencies WHERE iso_code = :currency LIMIT 1
            """), {"currency": request.currency}).scalar()
            if not currency_valid:
                raise HTTPException(status_code=400, detail=f"Invalid currency: {request.currency}")
        
        # Prepare order data
        order_data = {
            "tenant_id": request.tenant_id,
            "site_id": request.site_id,
            "store_id": request.store_id,
            "customer_id": request.customer_id,
            "currency": request.currency,
            "items": [{"offer_id": item.offer_id, "quantity": item.quantity} for item in request.items],
            "payment_method": request.payment_method,
            "correlation_id": correlation_id,
            "idempotency_key": request.idempotency_key
        }
        
        # Execute saga
        result = await order_saga.execute_order_saga(order_data)
        
        # Store event in event store
        await event_store.append_event(ServiceEvent(
            event_type=ServiceEventType.ORDER_CREATED,
            service_name=SERVICE_NAME,
            correlation_id=correlation_id,
            data=result,
            metadata={"enhanced": True, "saga_completed": True, "version": "2.0"},
            timestamp=datetime.now(timezone.utc)
        ))
        
        metrics.histogram("endpoint.create_order_v2.duration").observe((datetime.now() - start_time).total_seconds())
        
        return OrderV2Response(
            order_id=str(result["order_id"]),
            status=result.get("status", "completed"),
            total_minor=result["total_minor"],
            currency=result["currency"],
            created_at=datetime.now(timezone.utc),
            saga_id=correlation_id
        )
        
    except Exception as e:
        metrics.counter("endpoint.create_order_v2.error").inc()
        logger.error(f"Order creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/v2")
async def list_orders_v2(tenant_id: str = Query(...), limit: int = Query(50)):
    """List orders using V2 architecture"""
    start_time = datetime.now()
    metrics.counter("endpoint.list_orders_v2.called").inc()
    
    try:
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=tenant_id)
            
            rows = db.execute(text("""
                SELECT order_id, tenant_id, site_id, store_id, customer_id, 
                       total_minor, currency, status, created_at
                  FROM orders_new
                 WHERE tenant_id=:t
                 ORDER BY created_at DESC
                 LIMIT :l
            """), {"t": tenant_id, "l": limit}).all()
            
            orders = []
            for r in rows:
                # Get order items
                items = db.execute(text("""
                    SELECT item_id, offer_id, quantity, unit_price_minor, total_price_minor
                      FROM order_items_new
                     WHERE order_id=:oid
                """), {"oid": r[0]}).all()
                
                orders.append({
                    "order_id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "site_id": str(r[2]) if r[2] else None,
                    "store_id": str(r[3]) if r[3] else None,
                    "customer_id": str(r[4]),
                    "total_minor": int(r[5]),
                    "currency": r[6],
                    "status": r[7],
                    "created_at": r[8].isoformat(),
                    "items": [
                        {
                            "item_id": str(item[0]),
                            "offer_id": str(item[1]),
                            "quantity": int(item[2]),
                            "unit_price_minor": int(item[3]),
                            "total_price_minor": int(item[4])
                        }
                        for item in items
                    ]
                })
            
            metrics.histogram("endpoint.list_orders_v2.duration").observe((datetime.now() - start_time).total_seconds())
            return {"orders": orders, "count": len(orders)}
            
    except Exception as e:
        metrics.counter("endpoint.list_orders_v2.error").inc()
        logger.error(f"Failed to list orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/v2/{order_id}")
async def get_order_v2(order_id: str = Path(...)):
    """Get order details using V2 architecture"""
    start_time = datetime.now()
    metrics.counter("endpoint.get_order_v2.called").inc()
    
    try:
        with SessionLocal() as db:
            # Get order header
            header = db.execute(text("""
                SELECT order_id, tenant_id, site_id, store_id, customer_id, 
                       total_minor, currency, status, payment_method, created_at
                  FROM orders_new
                 WHERE order_id=:id
            """), {"id": order_id}).first()
            
            if not header:
                raise HTTPException(status_code=404, detail="Order not found")
            
            # Get order items
            items = db.execute(text("""
                SELECT item_id, offer_id, quantity, unit_price_minor, total_price_minor
                  FROM order_items_new
                 WHERE order_id=:id
            """), {"id": order_id}).all()
            
            # Get sub orders if any
            sub_orders = db.execute(text("""
                SELECT sub_order_id, vendor_id, status, total_minor, currency, created_at
                  FROM sub_orders
                 WHERE order_id=:id
            """), {"id": order_id}).all()
            
            metrics.histogram("endpoint.get_order_v2.duration").observe((datetime.now() - start_time).total_seconds())
            
            return {
                "order": {
                    "order_id": str(header[0]),
                    "tenant_id": str(header[1]),
                    "site_id": str(header[2]) if header[2] else None,
                    "store_id": str(header[3]) if header[3] else None,
                    "customer_id": str(header[4]),
                    "total_minor": int(header[5]),
                    "currency": header[6],
                    "status": header[7],
                    "payment_method": header[8],
                    "created_at": header[9].isoformat()
                },
                "items": [
                    {
                        "item_id": str(item[0]),
                        "offer_id": str(item[1]),
                        "quantity": int(item[2]),
                        "unit_price_minor": int(item[3]),
                        "total_price_minor": int(item[4])
                    }
                    for item in items
                ],
                "sub_orders": [
                    {
                        "sub_order_id": str(sub[0]),
                        "vendor_id": str(sub[1]),
                        "status": sub[2],
                        "total_minor": int(sub[3]),
                        "currency": sub[4],
                        "created_at": sub[5].isoformat()
                    }
                    for sub in sub_orders
                ]
            }
            
    except HTTPException:
        raise
    except Exception as e:
        metrics.counter("endpoint.get_order_v2.error").inc()
        logger.error(f"Failed to get order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/orders/v2/{order_id}/returns")
async def create_return_v2(order_id: str = Path(...), payload: ReturnV2Payload = Body(...)):
    """Create a return for an order"""
    start_time = datetime.now()
    metrics.counter("endpoint.create_return_v2.called").inc()
    
    try:
        return_id = generate_time_sortable_uuid()
        
        with SessionLocal() as db:
            # Query tenant_id from orders_new table
            tenant = db.execute(text("SELECT tenant_id FROM orders_new WHERE order_id=:o"), {"o": order_id}).scalar()
            if not tenant:
                raise HTTPException(404, "Order not found")
            set_rls_context(db, tenant_id=str(tenant))
            
            db.execute(text("""
                INSERT INTO returns(return_id, order_id, reason, status, total_minor, currency, created_at)
                VALUES(:return_id, :order_id, :reason, 'pending', :total_minor, :currency, NOW())
            """), {
                "return_id": return_id,
                "order_id": order_id,
                "reason": payload.reason,
                "total_minor": payload.total_minor,
                "currency": payload.currency
            })
            
            db.commit()
            
            metrics.histogram("endpoint.create_return_v2.duration").observe((datetime.now() - start_time).total_seconds())
            
            return {
                "return_id": return_id,
                "order_id": order_id,
                "status": "pending",
                "reason": payload.reason,
                "total_minor": payload.total_minor,
                "currency": payload.currency
            }
            
    except Exception as e:
        metrics.counter("endpoint.create_return_v2.error").inc()
        logger.error(f"Failed to create return: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/orders/v2/refunds")
async def create_refund_v2(payload: RefundV2Payload = Body(...)):
    """Create a refund for an order or return"""
    start_time = datetime.now()
    metrics.counter("endpoint.create_refund_v2.called").inc()
    
    try:
        refund_id = generate_time_sortable_uuid()
        
        with SessionLocal() as db:
            # Query tenant_id from orders_new table
            tenant = db.execute(text("SELECT tenant_id FROM orders_new WHERE order_id=:o"), {"o": payload.order_id}).scalar()
            if not tenant:
                raise HTTPException(404, "Order not found")
            set_rls_context(db, tenant_id=str(tenant))
            
            db.execute(text("""
                INSERT INTO refunds(refund_id, return_id, order_id, amount_minor, currency, status, created_at)
                VALUES(:refund_id, :return_id, :order_id, :amount_minor, :currency, 'pending', NOW())
            """), {
                "refund_id": refund_id,
                "return_id": payload.return_id,
                "order_id": payload.order_id,
                "amount_minor": payload.amount_minor,
                "currency": payload.currency
            })
            
            db.commit()
            
            metrics.histogram("endpoint.create_refund_v2.duration").observe((datetime.now() - start_time).total_seconds())
            
            return {
                "refund_id": refund_id,
                "return_id": payload.return_id,
                "order_id": payload.order_id,
                "amount_minor": payload.amount_minor,
                "currency": payload.currency,
                "status": "pending"
            }
            
    except Exception as e:
        metrics.counter("endpoint.create_refund_v2.error").inc()
        logger.error(f"Failed to create refund: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ---- Enhanced Endpoints ----
@app.get("/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status"""
    return service_circuit_breaker.get_all_states()

@app.get("/events/metrics")
async def get_event_metrics():
    """Get event system metrics"""
    return service_bus.get_service_metrics()

@app.get("/sagas/{saga_id}")
async def get_saga_status(saga_id: str):
    """Get saga execution status"""
    status = saga_orchestrator.get_saga_status(saga_id)
    if not status:
        raise HTTPException(status_code=404, detail="Saga not found")
    return status

@app.get("/events/{entity_id}")
async def get_entity_events(entity_id: str, limit: int = 100):
    """Get events for an entity"""
    events = await event_store.get_events(entity_id=entity_id, limit=limit)
    return {"entity_id": entity_id, "events": events}

@app.get("/services")
async def get_services():
    """Get all registered services"""
    return service_registry.get_all_services()

@app.get("/system/health")
async def get_system_health():
    """Get overall system health"""
    return await health_monitor.check_system_health()

# ---- Legacy Endpoints (for backward compatibility) ----
# Legacy endpoints removed - use /orders/v2 for enhanced features
# @app.post("/orders")
# def create_order(payload: NewOrder = Body(...)):
    """
    Create an order (LEGACY ENDPOINT - DEPRECATED).
    Use /orders/v2 for new V2 architecture with enhanced features.
    If payment method is 'stripe', an external payment intent is created and the order
    is set to payment_pending; complete card on the client and then call POST /orders/{id}/settle.
    If method 'trade' (default), the order is completed immediately and a Trade invoice is posted.
    """
    logger.warning("Legacy order endpoint used - consider migrating to /orders/v2")
    metrics.counter("endpoint.create_order_legacy.called").inc()
    when = datetime.utcnow()
    with SessionLocal() as db:
        logger.info(f"order_create_started tenant={payload.tenant_id} site={payload.site_id} store={payload.store_id} shopper={payload.shopper_id} items={len(payload.items)} method={payload.payment_method or '-'}")

        # 1) price validation using new pricing engine
        validated = []
        totals = 0
        pricing_context = {
            "user_role": "customer",  # TODO: Get actual user role from user service
            "order_time": when.isoformat()
        }
        
        for it in payload.items:
            # Try to get calculated price from pricing service
            try:
                import httpx
                pricing_response = httpx.post(
                    f"{os.getenv('PRICING_BASE_URL', 'http://localhost:8209')}/pricing/calculate",
                    json={
                        "store_id": payload.store_id,
                        "sku": it.sku,
                        "user_id": payload.shopper_id,
                        "currency": payload.currency,
                        "quantity": int(it.qty),
                        "force_recalculate": False
                    },
                    timeout=5.0
                )
                if pricing_response.status_code == 200:
                    pricing_data = pricing_response.json()
                    unit = pricing_data["final_price_gbp"]  # Price in pounds
                    base_price = pricing_data.get("base_price_gbp", pricing_data["final_price_gbp"])  # Price in pounds
                    logger.info(f"pricing_engine_used sku={it.sku} base={base_price} final={unit} rules={len(pricing_data.get('applied_rules', []))} promos={len(pricing_data.get('applied_promotions', []))}")
                else:
                    raise Exception(f"Pricing service error: {pricing_response.status_code}")
            except Exception as e:
                logger.warning(f"pricing_service_fallback sku={it.sku} error={str(e)}")
                # Fallback to old pricing logic
                row = db.execute(text("""
                    SELECT unit_minor FROM prices
                     WHERE sku=:s AND currency=:c AND active = TRUE
                """), {"s": it.sku, "c": payload.currency}).first()
                if not row:
                    logger.warning(f"no_active_price sku={it.sku} currency={payload.currency}")
                    raise HTTPException(status_code=400, detail=f"No active price for SKU {it.sku} {payload.currency}")
                unit = float(row[0])  # Now in pounds
            
            validated.append({"sku": it.sku, "qty": int(it.qty), "unit_minor": unit})
            totals += unit * int(it.qty)
        logger.info(f"order_price_validated total_minor={totals} currency={payload.currency}")

        # 2) budget / approvals
        cc_id = _user_cc(db, payload.shopper_id)
        if not cc_id:
            raise HTTPException(status_code=400, detail="Shopper has no cost centre")
        snap = _budget_snapshot(db, cc_id)
        if not snap:
            raise HTTPException(status_code=400, detail="No budget configured")

        remaining = snap["limit_minor"] - snap["spent_minor"]
        overspend = max(0, totals - max(0, remaining))
        if overspend > 0:
            covered = _approval_cover_and_consume(db, cc_id, payload.shopper_id, overspend)
            if not covered:
                logger.info(f"budget_blocked cc={cc_id} remaining={remaining} need={totals}")
                raise HTTPException(status_code=403, detail="Budget would overspend (hard block); no approval cover")
        logger.info(f"budget_ok cc={cc_id} remaining_before={remaining} total={totals}")

        # 3) decide method: explicit > tenant pref > default trade
        method = payload.payment_method
        if method is None:
            pm = db.execute(text("SELECT method FROM payment_preferences WHERE tenant_id=:t"),
                            {"t": payload.tenant_id}).scalar()
            method = (pm or "trade")

        # ---- STRIPE path ----
        if method == "stripe":
            db.execute(text("""
                INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                                   provider, provider_order_id, total_minor, currency, status, occurred_at)
                VALUES(:t,:s,:st,:u,:cc,'stripe','orders-api',:tot,:cur,'payment_pending',:occ)
            """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id,
                   "u": payload.shopper_id, "cc": cc_id, "tot": totals, "cur": payload.currency, "occ": when})
            order_id = db.execute(text("SELECT currval(pg_get_serial_sequence('orders','order_id'))")).scalar()

            for it in validated:
                name = db.execute(text("SELECT name FROM products WHERE sku=:sku"), {"sku": it["sku"]}).scalar() or it["sku"]
                db.execute(text("""
                    INSERT INTO order_items(order_id, sku, name, qty, price_minor)
                    VALUES(:oid,:sku,:name,:qty,:price)
                """), {"oid": order_id, "sku": it["sku"], "name": name, "qty": it["qty"], "price": it["unit_minor"]})
            db.commit()

            try:
                r = requests.post(
                    f"{PAYMENTS_BASE}/payments/stripe/payment-intent",
                    json={
                        "tenant_id": payload.tenant_id,
                        "order_id": str(order_id),
                        "site_id": payload.site_id,
                        "amount_minor": totals,
                        "currency": payload.currency
                    },
                    timeout=10
                )
                r.raise_for_status()
                pi = r.json()
            except Exception as e:
                logger.exception(f"stripe_pi_error order_id={order_id} err={str(e)}")
                db.execute(text("UPDATE orders SET status='payment_failed' WHERE order_id=:id"), {"id": order_id})
                db.commit()
                raise HTTPException(status_code=502, detail=f"stripe error: {e}")

            db.execute(
                text("UPDATE orders SET provider_order_id=:pi WHERE order_id=:id"),
                {"pi": pi.get("payment_intent_id"), "id": order_id},
            )
            db.commit()
            logger.info(f"order_created_stripe order_id={order_id} total={totals} currency={payload.currency} pi={pi.get('payment_intent_id')}")

            return {
                "ok": True,
                "order_id": int(order_id),
                "status": "payment_pending",
                "total_gbp": totals,
                "currency": payload.currency,
                "payment": {
                    "provider": "stripe",
                    "payment_intent_id": pi.get("payment_intent_id"),
                    "client_secret": pi.get("client_secret"),
                    "status": pi.get("status"),
                }
            }

        # ---- TRADE path ----
        db.execute(text("""
            INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                               provider, provider_order_id, total_minor, currency, status, occurred_at)
            VALUES(:t,:s,:st,:u,:cc,'manual','orders-api',:tot,:cur,'completed',:occ)
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id,
               "cc": cc_id, "tot": totals, "cur": payload.currency, "occ": when})
        order_id = db.execute(text("SELECT currval(pg_get_serial_sequence('orders','order_id'))")).scalar()

        for it in validated:
            name = db.execute(text("SELECT name FROM products WHERE sku=:sku"), {"sku": it["sku"]}).scalar() or it["sku"]
            db.execute(text("""
                INSERT INTO order_items(order_id, sku, name, qty, price_minor)
                VALUES(:oid,:sku,:name,:qty,:price)
            """), {"oid": order_id, "sku": it["sku"], "name": name, "qty": it["qty"], "price": it["unit_minor"]})

        # Ledger (CC spend -> Tenant clearing)
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:s,:st,'order',:ref,'Orders API')
        """), {"t": payload.tenant_id, "amt": totals, "cur": payload.currency, "cc": cc_id,
               "s": payload.site_id, "st": payload.store_id, "ref": str(order_id)})
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:s,:st,'order',:ref,'Orders API')
        """), {"t": payload.tenant_id, "amt": totals, "cur": payload.currency, "cc": cc_id,
               "s": payload.site_id, "st": payload.store_id, "ref": str(order_id)})

        # Budget spend
        db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                   {"amt": totals, "cc": cc_id})

        # Usage events + daily agg
        db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:s,:st,'orders',:u,1,:occ)
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "occ": when})
        _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "orders", 1)

        # Unique shopper of day
        exist = db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:s,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "d": when.date()}).first()
        if not exist:
            db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:s,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "occ": when})
            _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "unique_shoppers", 1)

        # Inventory decrements
        _apply_inventory_decrements(db, payload.store_id, [{"sku": it["sku"], "qty": it["qty"]} for it in validated])

        # Trade invoice via Billing helper
        create_trade_invoice_if_applicable(
            db, payload.tenant_id, int(order_id), totals, payload.currency,
            payload.site_id, payload.store_id
        )

        db.commit()

        # Dev notification
        db.execute(text("""
            INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
            VALUES(:t,:u,'dev','Order receipt', :body)
        """), {"t": payload.tenant_id, "u": payload.shopper_id,
               "body": f"Order {order_id} total {totals} {payload.currency}"})
        db.commit()

        # Publish order events
        try:
            # Publish order created event
            order_created_event = Event(
                event_type=EventType.ORDER_CREATED,
                tenant_id=payload.tenant_id,
                site_id=payload.site_id,
                store_id=payload.store_id,
                user_id=payload.shopper_id,
                data={
                    "order_id": int(order_id),
                    "total_gbp": totals,
                    "currency": payload.currency,
                    "payment_method": "trade",
                    "items": validated
                },
                metadata={"service": "orders", "version": "0.9.2"}
            )
            
            # Publish order completed event
            order_completed_event = Event(
                event_type=EventType.ORDER_COMPLETED,
                tenant_id=payload.tenant_id,
                site_id=payload.site_id,
                store_id=payload.store_id,
                user_id=payload.shopper_id,
                data={
                    "order_id": int(order_id),
                    "total_gbp": totals,
                    "currency": payload.currency,
                    "payment_method": "trade",
                    "status": "completed"
                },
                metadata={"service": "orders", "version": "0.9.2"}
            )
            
            # Send events to Celery for async processing
            celery_app.send_task(
                "zeroque_common.events.tasks.process_order_event",
                args=[order_created_event.__dict__],
                queue="orders"
            )
            
            celery_app.send_task(
                "zeroque_common.events.tasks.process_order_event", 
                args=[order_completed_event.__dict__],
                queue="orders"
            )
            
            logger.info(f"order_events_published order_id={order_id} events=2")
            
        except Exception as e:
            logger.warning(f"Failed to publish order events: {str(e)}")

        logger.info(f"order_created_trade order_id={order_id} total={totals} currency={payload.currency}")
        return {
            "ok": True,
            "order_id": int(order_id),
            "total_gbp": totals,
            "currency": payload.currency,
            "payment": {"provider": "trade"},
            "deprecated": True,
            "message": "This is a legacy endpoint. Please use /orders/v2 for enhanced features."
        }

# @app.get("/orders")
# def list_orders(tenant_id: str = Query(...), limit: int = Query(50)):
    """List orders (LEGACY ENDPOINT - DEPRECATED). Use /orders/v2 for enhanced features."""
    logger.warning("Legacy list orders endpoint used - consider migrating to /orders/v2")
    metrics.counter("endpoint.list_orders_legacy.called").inc()
    
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, total_minor, currency, status, occurred_at
              FROM orders
             WHERE tenant_id=:t
             ORDER BY occurred_at DESC
             LIMIT :l
        """), {"t": tenant_id, "l": limit}).all()
        orders = [
            {"order_id": int(r[0]), "tenant_id": r[1], "site_id": r[2], "store_id": r[3], "shopper_id": r[4],
             "total_gbp": float(r[5]), "currency": r[6], "status": r[7], "occurred_at": str(r[8])}
            for r in rows
        ]
        return {
            "orders": orders,
            "deprecated": True,
            "message": "This is a legacy endpoint. Please use /orders/v2 for enhanced features."
        }

# @app.get("/orders/{order_id}")
# def get_order(order_id: int):
    """Get order details (LEGACY ENDPOINT - DEPRECATED). Use /orders/v2/{order_id} for enhanced features."""
    logger.warning("Legacy get order endpoint used - consider migrating to /orders/v2/{order_id}")
    metrics.counter("endpoint.get_order_legacy.called").inc()
    
    with SessionLocal() as db:
        header = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, total_minor, currency, status, occurred_at
              FROM orders
             WHERE order_id=:id
        """), {"id": order_id}).first()
        if not header:
            raise HTTPException(status_code=404, detail="order not found")
        items = db.execute(text("""
            SELECT sku, name, qty, price_minor FROM order_items WHERE order_id=:id
        """), {"id": order_id}).all()
        return {
            "order": {"order_id": int(header[0]), "tenant_id": header[1], "site_id": header[2], "store_id": header[3],
                      "shopper_id": header[4], "total_gbp": float(header[5]), "currency": header[6], "status": header[7],
                      "occurred_at": str(header[8])},
            "items": [{"sku": i[0], "name": i[1], "qty": int(i[2]), "price_gbp": float(i[3])} for i in items],
            "deprecated": True,
            "message": "This is a legacy endpoint. Please use /orders/v2/{order_id} for enhanced features."
        }

# @app.post("/orders/{order_id}/settle")
# def settle_order(order_id: int = Path(...)):
    """
    Finalize a Stripe order after payment succeeds (idempotent).
    """
    when = datetime.utcnow()
    with SessionLocal() as db:
        h = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, cost_centre_id, total_minor, currency, status
              FROM orders WHERE order_id=:id
        """), {"id": order_id}).first()
        if not h:
            raise HTTPException(status_code=404, detail="order not found")
        if h[8] == "completed":
            return {"ok": True, "order_id": order_id, "status": "completed"}  # idempotent
        if h[8] != "payment_pending":
            raise HTTPException(status_code=409, detail=f"order not pending; status={h[8]}")

        tenant_id, site_id, store_id, shopper_id, cc_id, total_minor, currency = h[1], h[2], h[3], h[4], h[5], int(h[6]), h[7]

        # Ledger
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:s,:st,'order',:ref,'Stripe order')
        """), {"t": tenant_id, "amt": total_minor, "cur": currency, "cc": cc_id,
               "s": site_id, "st": store_id, "ref": str(order_id)})
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:s,:st,'order',:ref,'Stripe order')
        """), {"t": tenant_id, "amt": total_minor, "cur": currency, "cc": cc_id,
               "s": site_id, "st": store_id, "ref": str(order_id)})

        # Budget spend
        db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                   {"amt": total_minor, "cc": cc_id})

        # Usage + daily aggregates
        db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:s,:st,'orders',:u,1,:occ)
        """), {"t": tenant_id, "s": site_id, "st": store_id, "u": shopper_id, "occ": when})
        _update_daily(db, when, tenant_id, site_id, store_id, "orders", 1)

        # Unique shopper of day
        exist = db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:s,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": tenant_id, "s": site_id, "st": store_id, "u": shopper_id, "d": when.date()}).first()
        if not exist:
            db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:s,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": tenant_id, "s": site_id, "st": store_id, "u": shopper_id, "occ": when})
            _update_daily(db, when, tenant_id, site_id, store_id, "unique_shoppers", 1)

        # Inventory out
        items = db.execute(text("SELECT sku, qty FROM order_items WHERE order_id=:id"), {"id": order_id}).all()
        _apply_inventory_decrements(db, store_id, [{"sku": i[0], "qty": int(i[1])} for i in items])

        # Mark done
        db.execute(text("UPDATE orders SET status='completed' WHERE order_id=:id"), {"id": order_id})
        db.commit()
        
        # Publish order completed event
        try:
            import asyncio
            asyncio.create_task(publish_order_completed(
                tenant_id=tenant_id,
                order_id=order_id,
                site_id=site_id,
                store_id=store_id,
                user_id=shopper_id,
                total_minor=total_minor,
                currency=currency,
                payment_method="stripe"
            ))
        except Exception as e:
            logger.warning(f"Failed to publish order completed event: {str(e)}")
        
        logger.info(f"order_settled order_id={order_id} total={total_minor} currency={currency}")
        return {"ok": True, "order_id": order_id, "status": "completed"}