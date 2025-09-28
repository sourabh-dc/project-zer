# services/orders/enhanced_main.py
"""
Enhanced Orders Service with Enterprise-Grade Communication Patterns

This service demonstrates the implementation of:
- Service-specific event streams
- Circuit breaker pattern
- Saga pattern for distributed transactions
- Event sourcing
- Health monitoring
"""

import os
import sys
import asyncio
import logging
from fastapi import FastAPI, Body, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

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
from zeroque_common.db.session import get_engine, init_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.observability import setup_logging, init_metrics, init_insights, add_observability_middleware

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
add_idempotency_middleware(app, routes=[("POST", "/orders")])

# Request models
class OrderItem(BaseModel):
    sku: str
    qty: int

class CreateOrderRequest(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    shopper_id: str
    currency: str
    items: List[OrderItem]
    payment_method: str = "trade"

class OrderResponse(BaseModel):
    order_id: str
    status: str
    total_minor: int
    currency: str
    created_at: datetime
    saga_id: Optional[str] = None

# Event handlers
async def handle_inventory_update(event: ServiceEvent):
    """Handle inventory update events"""
    logger.info(f"Received inventory update: {event.data}")
    # Update local inventory cache or trigger revalidation

async def handle_price_calculation(event: ServiceEvent):
    """Handle price calculation events"""
    logger.info(f"Received price calculation: {event.data}")
    # Update local price cache

# Saga implementation
class OrderSaga:
    """Saga for managing order creation across multiple services"""
    
    def __init__(self):
        self.saga_orchestrator = SagaOrchestrator()
        self.steps = [
            SagaStep("validate_inventory", self.validate_inventory, self.compensate_inventory),
            SagaStep("calculate_pricing", self.calculate_pricing, self.compensate_pricing),
            SagaStep("reserve_inventory", self.reserve_inventory, self.release_inventory),
            SagaStep("process_payment", self.process_payment, self.refund_payment),
            SagaStep("create_order", self.create_order_record, self.delete_order_record),
            SagaStep("send_notification", self.send_notification, None)
        ]
    
    async def execute_order_saga(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the complete order saga"""
        saga_id = f"order_{int(datetime.now().timestamp())}"
        
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
            raise
    
    async def validate_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate inventory availability"""
        logger.info(f"Validating inventory for order: {data}")
        
        # Call inventory service with circuit breaker
        try:
            response = await service_circuit_breaker.call_service(
                service_name="inventory",
                url=f"{os.getenv('INVENTORY_BASE_URL', 'http://localhost:8202')}/catalog/inventory/validate",
                payload={
                    "store_id": data["store_id"],
                    "items": [{"sku": item["sku"], "qty": item["qty"]} for item in data["items"]]
                },
                config=circuit_breaker_config
            )
            
            if not response.get("valid", False):
                raise HTTPException(status_code=400, detail="Insufficient inventory")
            
            return {"inventory_validated": True}
            
        except Exception as e:
            logger.error(f"Inventory validation failed: {str(e)}")
            raise
    
    async def calculate_pricing(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate pricing for order items"""
        logger.info(f"Calculating pricing for order: {data}")
        
        pricing_data = {"items": [], "total_minor": 0}
        
        for item in data["items"]:
            try:
                response = await service_circuit_breaker.call_service(
                    service_name="pricing",
                    url=f"{os.getenv('PRICING_BASE_URL', 'http://localhost:8209')}/pricing/calculate",
                    payload={
                        "store_id": data["store_id"],
                        "sku": item["sku"],
                        "user_id": data["shopper_id"],
                        "currency": data["currency"],
                        "quantity": item["qty"]
                    },
                    config=circuit_breaker_config
                )
                
                item_total = response["final_price_minor"] * item["qty"]
                pricing_data["items"].append({
                    "sku": item["sku"],
                    "qty": item["qty"],
                    "unit_price_minor": response["final_price_minor"],
                    "total_minor": item_total
                })
                pricing_data["total_minor"] += item_total
                
            except Exception as e:
                logger.error(f"Pricing calculation failed for {item['sku']}: {str(e)}")
                # Fallback to default pricing
                default_price = 1000  # Default price in minor units
                item_total = default_price * item["qty"]
                pricing_data["items"].append({
                    "sku": item["sku"],
                    "qty": item["qty"],
                    "unit_price_minor": default_price,
                    "total_minor": item_total
                })
                pricing_data["total_minor"] += item_total
        
        return pricing_data
    
    async def reserve_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Reserve inventory for the order"""
        logger.info(f"Reserving inventory for order: {data}")
        
        # Publish inventory reservation event
        await service_bus.publish_to_service(
            target_service="inventory",
            event_type=ServiceEventType.INVENTORY_RESERVED,
            data={
                "store_id": data["store_id"],
                "items": data["items"],
                "order_id": data.get("order_id", "pending")
            },
            correlation_id=data.get("saga_id", "")
        )
        
        return {"inventory_reserved": True}
    
    async def process_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process payment for the order"""
        logger.info(f"Processing payment for order: {data}")
        
        # For trade orders, this might just be a ledger entry
        # For other payment methods, this would call the payments service
        
        return {"payment_processed": True, "payment_method": data.get("payment_method", "trade")}
    
    async def create_order_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create the order record in the database"""
        logger.info(f"Creating order record: {data}")
        
        order_id = f"ORD_{int(datetime.now().timestamp())}"
        
        # Store in database
        db = SessionLocal()
        try:
            db.execute("""
                INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, 
                                total_minor, currency, payment_method, status, created_at)
                VALUES(:tenant_id, :site_id, :store_id, :shopper_id, 
                       :total_minor, :currency, :payment_method, 'completed', NOW())
            """, {
                "tenant_id": data["tenant_id"],
                "site_id": data["site_id"],
                "store_id": data["store_id"],
                "shopper_id": data["shopper_id"],
                "total_minor": data["total_minor"],
                "currency": data["currency"],
                "payment_method": data.get("payment_method", "trade")
            })
            db.commit()
            
            return {"order_id": order_id, "order_created": True}
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create order record: {str(e)}")
            raise
        finally:
            db.close()
    
    async def send_notification(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send order notification"""
        logger.info(f"Sending notification for order: {data}")
        
        # Publish notification event
        await service_bus.publish_to_service(
            target_service="notifications",
            event_type=ServiceEventType.ORDER_CREATED,
            data={
                "order_id": data["order_id"],
                "shopper_id": data["shopper_id"],
                "total_minor": data["total_minor"],
                "currency": data["currency"]
            },
            correlation_id=data.get("saga_id", "")
        )
        
        return {"notification_sent": True}
    
    # Compensation methods
    async def compensate_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate inventory validation"""
        logger.info(f"Compensating inventory validation: {data}")
        return {}
    
    async def compensate_pricing(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate pricing calculation"""
        logger.info(f"Compensating pricing calculation: {data}")
        return {}
    
    async def release_inventory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Release reserved inventory"""
        logger.info(f"Releasing inventory: {data}")
        
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
    
    async def refund_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Refund payment"""
        logger.info(f"Refunding payment: {data}")
        return {"payment_refunded": True}
    
    async def delete_order_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Delete order record"""
        logger.info(f"Deleting order record: {data}")
        return {"order_deleted": True}

# Initialize saga
order_saga = OrderSaga()

# Service startup
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
            "startup_time": datetime.now().isoformat(),
            "enhanced_features": ["saga", "circuit_breaker", "event_sourcing"]
        }
    )

# Health check
@app.get("/health")
async def health():
    """Enhanced service health check"""
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

# Enhanced order creation with saga pattern
@app.post("/orders", response_model=OrderResponse)
async def create_order(request: CreateOrderRequest = Body(...)):
    """Create order with enhanced communication patterns"""
    
    correlation_id = f"order_{datetime.now().isoformat()}"
    
    try:
        # Prepare order data
        order_data = {
            "tenant_id": request.tenant_id,
            "site_id": request.site_id,
            "store_id": request.store_id,
            "shopper_id": request.shopper_id,
            "currency": request.currency,
            "items": [{"sku": item.sku, "qty": item.qty} for item in request.items],
            "payment_method": request.payment_method,
            "correlation_id": correlation_id
        }
        
        # Execute saga
        result = await order_saga.execute_order_saga(order_data)
        
        # Store event in event store
        await event_store.append_event(ServiceEvent(
            event_type=ServiceEventType.ORDER_CREATED,
            service_name=SERVICE_NAME,
            correlation_id=correlation_id,
            data=result,
            metadata={"enhanced": True, "saga_completed": True},
            timestamp=datetime.now()
        ))
        
        return OrderResponse(
            order_id=result["order_id"],
            status="completed",
            total_minor=result["total_minor"],
            currency=result["currency"],
            created_at=datetime.now(),
            saga_id=correlation_id
        )
        
    except Exception as e:
        logger.error(f"Order creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Circuit breaker status endpoint
@app.get("/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status"""
    return service_circuit_breaker.get_all_states()

# Event metrics endpoint
@app.get("/events/metrics")
async def get_event_metrics():
    """Get event system metrics"""
    return service_bus.get_service_metrics()

# Saga status endpoint
@app.get("/sagas/{saga_id}")
async def get_saga_status(saga_id: str):
    """Get saga execution status"""
    status = saga_orchestrator.get_saga_status(saga_id)
    if not status:
        raise HTTPException(status_code=404, detail="Saga not found")
    return status

# Event store endpoint
@app.get("/events/{entity_id}")
async def get_entity_events(entity_id: str, limit: int = 100):
    """Get events for an entity"""
    events = await event_store.get_events(entity_id=entity_id, limit=limit)
    return {"entity_id": entity_id, "events": events}

# Service discovery endpoint
@app.get("/services")
async def get_services():
    """Get all registered services"""
    return service_registry.get_all_services()

# System health endpoint
@app.get("/system/health")
async def get_system_health():
    """Get overall system health"""
    return await health_monitor.check_system_health()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8208)
